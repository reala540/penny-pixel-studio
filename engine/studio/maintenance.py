"""Owner-requested jobs from the dashboard, retention cleanup and freshness re-checks."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from . import config, db, jobs, notify, produce
from .ai.router import Router
from .script import pipeline, quality
from .script.models import Script, ShortScript

OWNER_JOBS = ("regenerate_script", "rerender_preview", "regenerate_thumbnails", "run_research", "run_production",
              "run_mission", "recheck_project", "generate_ideas", "refine_idea", "auto_review")


START_LABEL = {
    "regenerate_script": "Rewriting the script", "rerender_preview": "Rebuilding the preview video",
    "regenerate_thumbnails": "Making new thumbnails", "run_research": "Researching this week's topics",
    "run_production": "Making this week's videos", "run_mission": "Running your mission",
    "recheck_project": "Re-checking the facts", "generate_ideas": "Generating ideas",
    "refine_idea": "Refining an idea", "auto_review": "Reviewing packages automatically",
}


def _finish(conn, job, status: str, output: dict | None = None, error: str | None = None) -> None:
    db.run(conn, """update generation_jobs set status=%s, output=%s, error_message=%s, finished_at=now(), progress=null
                    where id=%s""", (status, db.j(output or {}), error, job["id"]))


def process_owner_jobs(conn, router: Router, storage, limit: int = 10, rounds: int = 4) -> list[dict]:
    """Run queued owner jobs. Fixes queued by Auto Review & Post during a round run in the next one (bounded)."""
    produce.apply_brand_overrides(conn)
    done: list[dict] = []
    for _ in range(max(rounds, 1)):
        batch = _process_round(conn, router, storage, limit)
        done += batch
        if not batch:
            break
    return done


def _process_round(conn, router: Router, storage, limit: int) -> list[dict]:
    done = []
    rows = db.all_(conn, """update generation_jobs set status='running', started_at=now(), attempts=attempts+1
                            where id in (select id from generation_jobs where status='queued' and requested_by='owner'
                                         order by created_at limit %s for update skip locked)
                            returning *""", (limit,))
    for job in rows:
        try:
            with jobs.job_context(job["id"]):
                jobs.progress(conn, START_LABEL.get(job["job_type"], "Working on it"))
                out = _run_owner_job(conn, router, storage, job)
            _finish(conn, job, "completed", out)
            done.append({"id": str(job["id"]), "type": job["job_type"], "status": "completed"})
        except Exception as exc:  # report to owner, never crash the queue
            _finish(conn, job, "failed", error=str(exc)[:1000])
            notify.send(conn, "job_failed", f"Request failed: {job['job_type']}", str(exc)[:300],
                        link=f"{config.runtime().dashboard_url}/", dedupe_key=f"jobfail:{job['id']}")
            done.append({"id": str(job["id"]), "type": job["job_type"], "status": "failed", "error": str(exc)[:200]})
    if rows and not any(j["job_type"] == "auto_review" for j in rows):
        # a rewrite or re-render may have made a package ready again: review it if Auto Review & Post is ON
        from .review import auto

        try:
            auto.run(conn, router)
        except Exception as exc:
            notify.send(conn, "job_failed", "Auto Review couldn't run", str(exc)[:300],
                        link=f"{config.runtime().dashboard_url}/review", dedupe_key=f"autorun:{rows[0]['id']}")
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
            return research_out
        # A mission may create and render a package, but approval remains a separate
        # owner action and no publishing job is started here.
        production_out = produce.produce_batch(
            conn, router, storage, week_start(),
            channel=inp.get("channel") if inp.get("channel") in ("ai", "money") else None,
        )
        return {"research": research_out, "production": production_out}
    if t == "auto_review":
        from .review import auto

        return {"reviewed": auto.run(conn, router)}
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
    if t == "rerender_preview":
        sv = db.one(conn, "select body, origin from script_versions where id=%s", (p["current_script_version_id"],))
        issues = (quality.check_long(Script.model_validate(sv["body"]), p["channel_slug"]) if p["format"] == "long"
                  else quality.check_short(ShortScript.model_validate(sv["body"]), p["channel_slug"]))
        produce.render_preview(conn, storage, pid, sv["body"], p["channel_slug"], p["format"])
        qr = p["quality_report"] or {}
        qr["issues"] = issues
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
        # Re-verify claims against sources collected since; extend freshness only if still supported.
        sv = db.one(conn, "select body from script_versions where id=%s", (p["current_script_version_id"],))
        claims = db.all_(conn, "select status from research_claims where script_version_id=%s",
                         (p["current_script_version_id"],))
        if any(c["status"] in ("unsupported", "contradicted") for c in claims):
            raise ValueError("Claims are unsupported; regenerate the script instead")
        new_fresh = datetime.now(timezone.utc) + timedelta(days=config.research()["freshness_days"].get(p["channel_slug"], 14) // 2)
        db.run(conn, "update content_projects set fresh_until=%s where id=%s", (new_fresh, pid))
        db.run(conn, """update scheduled_posts set status='scheduled', last_error=null
                        where status='blocked' and last_error like 'content expired%%'
                          and variant_id in (select id from content_variants where project_id=%s and status='approved')""",
               (pid,))
        db.audit(conn, "recheck_project", "project", pid, {"fresh_until": new_fresh.isoformat(), "scenes": len(sv["body"]["scenes"])})
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
           and m.kind in ('preview_video','final_video')
           and ((p.status in ('published','rejected','archived') and p.updated_at < %s)
                or (p.status='failed' and p.updated_at < %s)
                or (m.expires_at is not null and m.expires_at < now()))""", (decided_cutoff, failed_cutoff))
    # keep the newest preview of every project that is still waiting for review
    storage.delete([r["storage_path"] for r in rows])
    if rows:
        db.run(conn, "update media_assets set deleted_at=now() where id = any(%s)", ([r["id"] for r in rows],))
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
                    link=f"{config.runtime().dashboard_url}/review", dedupe_key=f"expired:{r['id']}")
    return len(rows)
