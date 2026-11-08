"""Owner-requested jobs from the dashboard, retention cleanup and freshness re-checks."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from . import config, db, jobs, links, notify, produce
from .ai.router import Router
from .script import pipeline, quality
from .script.models import Script, ShortScript

OWNER_JOBS = ("regenerate_script", "rerender_preview", "regenerate_thumbnails", "run_research", "run_production",
              "run_mission", "recheck_project", "generate_ideas", "refine_idea", "auto_review", "produce_idea",
              "check_providers", "remake_shorts", "preview_scene", "repair_package")


START_LABEL = {
    "regenerate_script": "Rewriting the script", "rerender_preview": "Rebuilding the preview video",
    "regenerate_thumbnails": "Making new thumbnails", "run_research": "Researching this week's topics",
    "run_production": "Making this week's videos", "run_mission": "Running your mission",
    "recheck_project": "Re-checking the facts", "generate_ideas": "Generating ideas",
    "refine_idea": "Refining an idea", "auto_review": "Reviewing packages automatically",
    "produce_idea": "Making the package for your idea", "check_providers": "Testing the AI keys",
    "remake_shorts": "Making new Shorts", "preview_scene": "Previewing one scene",
    "repair_package": "Rechecking and repairing the package",
}


def _finish(conn, job, status: str, output: dict | None = None, error: str | None = None) -> None:
    db.run(conn, """update generation_jobs set status=%s, output=%s, error_message=%s, finished_at=now(), progress=null
                    where id=%s""", (status, db.j(output or {}), error, job["id"]))


def _ensure_current_review_policy(conn):
    """A queued older deployment may consume the activation job; replay it once on updated code."""
    if db.get_setting(conn,"auto_review_post",False) is not True:
        return
    db.run(conn,"""update generation_jobs set status='queued',finished_at=null,next_attempt_at=null,
        input=jsonb_set(input,'{activation_replayed}','true'::jsonb)
        where idempotency_key='auto-review:recovery-v2' and status='completed'
          and coalesce(output->>'review_policy','')<>'recovery_v2'
          and coalesce(input->>'activation_replayed','false')<>'true'""")


def process_owner_jobs(conn, router: Router, storage, limit: int = 10, rounds: int = 4) -> list[dict]:
    """Run queued owner jobs. Fixes queued by Auto Review & Post during a round run in the next one (bounded)."""
    _ensure_current_review_policy(conn)
    notify.retry_pending(conn)
    produce.apply_brand_overrides(conn)
    jobs.check_stop(conn)  # notes when this run started, so a later Stop & clear stops it
    _review_waiting_repairs(conn,router)
    done: list[dict] = []
    for _ in range(max(rounds, 1)):
        batch = _process_round(conn, router, storage, limit)
        done += batch
        if not batch:
            break
    from .review import replace

    try:  # held packages: reminders, and safer replacements when the owner hasn't decided in time
        out = replace.tick(conn, router, storage)
        if out.get("reminded") or out.get("replaced"):
            done.append({"type": "auto_replace", "status": "completed", **out})
    except Exception as exc:
        notify.send(conn, "job_failed", "Automatic replacement couldn't run", str(exc)[:300],
                    link=links.needs_you(), dedupe_key=f"replacefail:{datetime.now(timezone.utc):%Y%m%d%H}")
    return done


def _review_completed_job(conn, router, job):
    """Recheck each completed package before another long job can delay its approval."""
    from .review import auto
    if job["job_type"] == "auto_review" or not job.get("project_id") or not auto.mode_on(conn):
        return
    try:
        parent = db.one(conn,"select coalesce(parent_project_id,id) id from content_projects where id=%s",(job["project_id"],))
        if parent:
            auto.run(conn,router,[parent["id"]])
    except Exception as exc:
        notify.send(conn,"job_failed","Auto Review couldn't run",str(exc)[:300],
                    link=links.needs_you(),dedupe_key=f"autorun:{job['id']}")


def _review_waiting_repairs(conn, router):
    """Catch completed repairs left behind by an older queue process, once per unchecked version."""
    from .review import auto
    if not auto.mode_on(conn):
        return
    rows = db.all_(conn,"""select p.id,
        (select j.id from generation_jobs j where j.project_id=p.id and j.status='completed' and j.input->>'auto_fix'='true' order by j.finished_at desc limit 1) job_id
        from content_projects p where p.parent_project_id is null and p.status in ('ready_for_review','needs_attention')
        and exists(select 1 from generation_jobs j where j.project_id=p.id and j.status='completed' and j.input->>'auto_fix'='true')
        and not exists(select 1 from generation_jobs j where j.project_id=p.id and j.requested_by='owner' and j.status in ('queued','running'))
        and (select a.verdict from auto_reviews a where a.project_id=p.id order by a.created_at desc,a.attempt desc limit 1)='fixing'""")
    for row in rows:
        _review_completed_job(conn,router,{"job_type":"repair_catchup","project_id":row["id"],"id":row["job_id"]})


def _process_round(conn, router: Router, storage, limit: int) -> list[dict]:
    done = []
    for _ in range(limit):
        job = db.one(conn, """update generation_jobs set status='running', started_at=now(), updated_at=now(), attempts=attempts+1
                            where id = (select id from generation_jobs where status='queued' and requested_by='owner' and coalesce(next_attempt_at,now())<=now()
                                        order by created_at limit 1 for update skip locked)
                            returning *""")
        if job is None:
            break
        try:
            with jobs.job_context(job["id"]):
                jobs.progress(conn, START_LABEL.get(job["job_type"], "Working on it"))
                out = _run_owner_job(conn, router, storage, job)
                jobs.check_stop(conn)
            _finish(conn, job, "completed", out)
            done.append({"id": str(job["id"]), "type": job["job_type"], "status": "completed"})
            _review_completed_job(conn,router,job)
        except jobs.JobCancelled:
            _finish(conn, job, "cancelled")
            db.run(conn, """update content_projects set status='failed' where
                      (id=%s or id in (select project_id from generation_jobs where parent_job_id=%s))
                      and status in ('draft','scripting','verifying','rendering')""", (job['project_id'],job['id']))
            notify.send(conn, "job_cancelled", "Work cancelled", "Completed work was kept. Other projects are unchanged.",
                        link=links.job(job), dedupe_key=f"cancelled:{job['id']}")
            done.append({"id": str(job["id"]), "type": job["job_type"], "status": "cancelled"})
        except Exception as exc:  # report to owner, never crash the queue
            from .errors import TransientError, QuotaError
            current_job = db.one(conn,"select input from generation_jobs where id=%s",(job["id"],))
            current_input = (current_job or {}).get("input") or {}
            expected = current_input.get("resume_version") or current_input.get("expected_version")
            project = db.one(conn,"select current_script_version_id from content_projects where id=%s",(job["project_id"],)) if job["project_id"] else None
            if (current_input.get("auto_fix") and isinstance(exc,(TransientError,QuotaError)) and job["attempts"]<3
                    and current_input.get("recovery_stage") != "rendering" and project and expected
                    and str(project["current_script_version_id"])==str(expected)):
                retry_at = datetime.now(timezone.utc)+timedelta(minutes=15*job["attempts"])
                db.run(conn,"update generation_jobs set status='queued',next_attempt_at=%s,error_message=%s,progress=null where id=%s",(retry_at,str(exc)[:1000],job["id"]))
                done.append({"id":str(job["id"]),"type":job["job_type"],"status":"retrying"})
                continue
            _finish(conn, job, "failed", error=str(exc)[:1000])
            if current_input.get("auto_fix"):
                db.run(conn,"update content_projects set status='needs_attention' where id=%s and status='rendering'",(job["project_id"],))
            notify.send(conn, "job_failed", f"Request failed: {job['job_type']}", str(exc)[:300],
                        link=links.job(job), dedupe_key=f"jobfail:{job['id']}")
            done.append({"id": str(job["id"]), "type": job["job_type"], "status": "failed", "error": str(exc)[:200]})
    return done


def _project(conn, pid) -> dict:
    p = db.one(conn, "select * from content_projects where id=%s", (pid,))
    if not p:
        raise ValueError("project not found")
    return p


def _reset_variants(conn, pid) -> None:
    db.run(conn, """update content_variants set status='ready_for_review' where project_id=%s
                    and status in ('approved','needs_attention','ready_for_review')""", (pid,))


def _run_owner_job(conn, router: Router, storage, job: dict) -> dict:
    t, inp = job["job_type"], job["input"] or {}
    if t in ("run_research", "run_mission"):
        from .research.engine import week_start

        research_out = produce.research_batch(
            conn, router, week_start(), brief=str(inp.get("brief") or ""),
            channel=inp.get("channel") if inp.get("channel") in ("ai", "money") else None,
            n_models=max(1, min(int(inp.get("models") or 3), 5)),
        )
        if t == "run_research":
            notify.send(conn, "research_ready", "Your research is ready", "Open the researched ideas and sources.",
                        link=links.research_since(job.get("started_at") or job["created_at"]), dedupe_key=f"research:{job['id']}")
            return research_out
        # A mission may create and render a package, but approval remains a separate
        # owner action and no publishing job is started here.
        production_out = produce.produce_batch(
            conn, router, storage, week_start(),
            channel=inp.get("channel") if inp.get("channel") in ("ai", "money") else None,
        )
        return {"research": research_out, "production": production_out}
    if t == "produce_idea":
        # Exactly the selected idea. Not stopped by the publishing pause: nothing is posted here.
        return produce.produce_idea(conn, router, storage, content_idea_id=inp.get("content_idea_id"),
                                    generated_idea_id=inp.get("generated_idea_id"),
                                    channel=inp.get("channel") if inp.get("channel") in ("ai", "money") else None)
    if t == "check_providers":
        from .cli import run_provider_check

        only = str(inp.get("provider") or "") or None
        results = run_provider_check(conn, only)
        output = {"ok": sum(1 for r in results if r["status"] == "ok"), "checked": len(results)}
        notify.send(conn, "provider_check_ready", "AI service test finished", f"{output['ok']} of {output['checked']} services passed. Open AI services for model details.",
                    link=links.job(job), dedupe_key=f"keycheck:{job['id']}")
        return output
    if t == "auto_review":
        from .review import auto, recovery
        recovered = 0
        if auto.mode_on(conn) and inp.get("recover_final_checks"):
            for row in db.all_(conn,"""select distinct v.project_id from scheduled_posts sp join content_variants v on v.id=sp.variant_id
                    where sp.status='blocked' and sp.last_error like 'Final check:%'"""):
                recovered += bool(recovery.queue_final(conn,row["project_id"],[],"Previously blocked final check; repair the saved script against its evidence"))
        return {"review_policy":"recovery_v2","recovered": recovered,"reviewed": auto.run(conn, router)}
    if t == "generate_ideas":
        # Ideas only go to the Idea Library; nothing here starts research-to-production or publishing.
        from .ideas import generator

        trigger = inp.get("trigger") if inp.get("trigger") in ("manual", "scheduled", "regenerate") else "manual"
        overrides = inp.get("overrides") if isinstance(inp.get("overrides"), dict) else None
        with db.run_lock(conn, "ideas") as free:
            if not free:
                return {"skipped": "another idea run is in progress"}
            return generator.run(conn, router, trigger=trigger, job_id=job["id"], overrides=overrides)
    if t == "refine_idea":
        from .ideas import generator

        if not inp.get("idea_id") or not str(inp.get("note") or "").strip():
            raise ValueError("refine_idea needs idea_id and a note")
        return generator.refine(conn, router, inp["idea_id"], str(inp["note"]))
    if t == "run_production":
        from .research.engine import week_start

        return produce.produce_batch(conn, router, storage, week_start())
    pid = job["project_id"] or inp.get("project_id")
    p = _project(conn, pid)
    if t == "preview_scene":
        return produce.preview_scene(conn, storage, pid, int(inp.get("scene", -1)))
    if t == "repair_package":
        return produce.repair_package(conn, router, storage, pid, job_id=job["id"])
    if t == "remake_shorts":
        return produce.remake_shorts(conn, router, storage, pid, job_id=job["id"], note=str(inp.get("note") or "")[:500])
    if t == "rerender_preview":
        sv = db.one(conn, "select body, origin from script_versions where id=%s", (p["current_script_version_id"],))
        issues = (quality.check_long(Script.model_validate(sv["body"]), p["channel_slug"]) if p["format"] == "long"
                  else quality.check_short(ShortScript.model_validate(sv["body"]), p["channel_slug"]))
        produce.render_preview(conn, storage, pid, sv["body"], p["channel_slug"], p["format"])
        qr = p["quality_report"] or {}
        qr["issues"] = issues
        if "findings" in qr:  # the script's checks were rerun on this version: replace their findings
            qr["findings"] = [f for f in qr["findings"] if f.get("code") != "check"] + [
                {"kind": "blocker" if i in pipeline.blocking(issues) else "warning", "code": "check", "text": i}
                for i in issues]
        qr["owner_edited"] = sv["origin"] == "owner_edit"
        db.run(conn, "update content_projects set quality_report=%s, status='ready_for_review' where id=%s",
               (db.j(qr), pid))
        produce.final_status(conn, pid)
        _reset_variants(conn, pid)
        return {"issues": issues}
    if t == "regenerate_thumbnails":
        db.run(conn, "delete from generation_jobs where idempotency_key=%s", (f"thumbs:{pid}",))
        if inp.get("headlines"):
            db.run(conn, """update content_projects set recipe = jsonb_set(recipe, '{package,thumbnail_headlines}', %s)
                            where id=%s""", (db.j(inp["headlines"]), pid))
        return produce.make_thumbnails(conn, storage, pid, p["channel_slug"])
    if t == "regenerate_script" and inp.get("auto_fix"):
        from .review import recovery
        return recovery.repair(conn, router, storage, job)
    if t == "regenerate_script":
        if p["format"] != "long":
            raise ValueError("Regenerate the parent long video; Shorts are rebuilt from it")
        idea = db.one(conn, "select * from content_ideas where id=%s", (p["idea_id"],))
        sources = produce._sources_for(conn, list(idea["source_ids"]))
        angle = (idea.get("angle") or "") + (f"\nOwner request: {inp['instructions']}" if inp.get("instructions") else "")
        result = pipeline.write_long(router, p["channel_slug"], {"title": p["title"], "angle": angle}, sources)
        produce.save_script(conn, pid, result.script.model_dump(), "rewrite", result.trail, result.claims,
                            result.facts, sources)
        db.run(conn, "update content_projects set quality_report=%s where id=%s", (db.j(result.report), pid))
        produce.render_preview(conn, storage, pid, result.script.model_dump(), p["channel_slug"], "long")
        produce.final_status(conn, pid)
        _reset_variants(conn, pid)
        return {"issues": result.issues}
    if t == "recheck_project":
        from . import preflight
        records = preflight.check(conn, router, pid)
        new_fresh = datetime.now(timezone.utc) + timedelta(days=config.research()["freshness_days"].get(p["channel_slug"], 14) // 2)
        db.run(conn, "update content_projects set fresh_until=%s where id=%s", (new_fresh, pid))
        db.run(conn, """update scheduled_posts set status='scheduled', last_error=null
                        where status='blocked' and last_error like 'content expired%%'
                          and variant_id in (select id from content_variants where project_id=%s and status='approved')""",
               (pid,))
        db.audit(conn, "recheck_project", "project", pid, {"fresh_until": new_fresh.isoformat(), "claims_checked": len(records)})
        return {"fresh_until": new_fresh.isoformat()}
    raise ValueError(f"Unknown job type {t}")


def cleanup(conn, storage) -> dict:
    """Apply retention rules. Never deletes recipes, scripts, citations, licenses or post IDs."""
    ret = config.services()["retention"]
    now = datetime.now(timezone.utc)
    decided_cutoff = now - timedelta(days=ret["preview_days_after_decision"])
    failed_cutoff = now - timedelta(days=ret["failed_asset_days"])
    rows = db.all_(conn, """
        select m.id, m.storage_path from media_assets m join content_projects p on p.id=m.project_id
         where m.deleted_at is null and m.storage_path is not null
           and m.kind in ('preview_video','final_video','video_clip')
           -- a stock clip stays while any post of its project still has to be rendered and sent
           and (m.kind <> 'video_clip' or not exists (
                 select 1 from content_variants v join scheduled_posts sp on sp.variant_id = v.id
                  where v.project_id = p.id and sp.status in ('pending_approval','scheduled','publishing')))
           and ((p.status in ('published','rejected','archived') and p.updated_at < %s)
                or (p.status='failed' and p.updated_at < %s)
                or (m.expires_at is not null and m.expires_at < now()))""", (decided_cutoff, failed_cutoff))
    # keep the newest preview of every project that is still waiting for review
    storage.delete([r["storage_path"] for r in rows])
    if rows:
        db.run(conn, "update media_assets set deleted_at=now() where id = any(%s)", ([r["id"] for r in rows],))
    db.run(conn, "delete from model_output_checks where created_at < now() - interval '90 days'")
    old_jobs = db.run(conn, "delete from job_attempts where started_at < now() - interval '60 days'")
    usage = db.run(conn, "delete from provider_usage where created_at < now() - interval '400 days'")
    return {"previews_deleted": len(rows), "old_attempts": old_jobs, "old_usage_rows": usage}


def expire_stale(conn) -> int:
    """Block approved-but-unpublished time-sensitive posts whose facts went stale, and tell the owner."""
    rows = db.all_(conn, """
        update scheduled_posts sp set status='blocked', last_error='content expired: recheck before publishing'
          from content_variants v join content_projects p on p.id=v.project_id
         where sp.variant_id=v.id and sp.status in ('scheduled','pending_approval')
           and p.fresh_until is not null and p.fresh_until < sp.scheduled_at
        returning sp.id, p.title""")
    for r in rows:
        notify.send(conn, "expired", "Content needs a freshness re-check", r["title"],
                    link=links.project(r["id"]), dedupe_key=f"expired:{r['id']}")
    return len(rows)
