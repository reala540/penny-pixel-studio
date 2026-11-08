"""Bounded recovery for unpublished packages; published or ambiguous work is never rewritten."""

from .. import db, produce
from ..errors import NeedsReview
from ..script import pipeline
from ..script.models import Script


def head(conn, project_id):
    p = db.one(conn, "select * from content_projects where id=%s", (project_id,))
    return (
        db.one(
            conn,
            "select * from content_projects where id=%s",
            (p["parent_project_id"],),
        )
        if p and p["parent_project_id"]
        else p
    )


def invalidate(conn, project_id, expected=None):
    """Lock projects and posts before withdrawing approvals. No network calls in this transaction."""
    family = db.all_(
        conn,
        "select * from content_projects where id=%s or parent_project_id=%s order by parent_project_id nulls first,id for update",
        (project_id, project_id),
    )
    p = next((p for p in family if str(p["id"]) == str(project_id)), None)
    if not p or (expected and str(p["current_script_version_id"]) != str(expected)):
        raise NeedsReview("Package changed since the repair was requested")
    if p["status"] in ("rejected", "archived", "published"):
        raise NeedsReview(
            "Package was rejected, archived or published; automatic repair stopped"
        )
    ids = [p["id"] for p in family]
    posts = db.all_(
        conn,
        "select sp.* from scheduled_posts sp join content_variants v on v.id=sp.variant_id where v.project_id=any(%s) for update of sp",
        (ids,),
    )
    if any(s["status"] in ("publishing", "published") for s in posts) or db.one(
        conn,
        """select 1 from publish_attempts pa join scheduled_posts sp on sp.id=pa.scheduled_post_id
        join content_variants v on v.id=sp.variant_id where v.project_id=any(%s) and (pa.outcome='published' or (pa.cleared_at is null and (pa.outcome is null or pa.outcome='ambiguous'))) limit 1""",
        (ids,),
    ):
        raise NeedsReview(
            "Part of this package is published, uploading or ambiguous; automatic rewriting is held"
        )
    db.run(
        conn,
        "update content_projects set approved_script_version_id=null,status='needs_attention' where id=any(%s) and status not in ('rejected','archived')",
        (ids,),
    )
    db.run(
        conn,
        "update content_variants set status='needs_attention' where project_id=any(%s) and status not in ('published','rejected')",
        (ids,),
    )
    db.run(
        conn,
        """update scheduled_posts set status='pending_approval',locked_until=null,last_error='Automatic repair: approval withdrawn'
        where variant_id in (select id from content_variants where project_id=any(%s)) and status not in ('published','cancelled')""",
        (ids,),
    )
    return p


def queue_final(conn, project_id, records, reason, expected=None):
    from . import auto

    p = head(conn, project_id)
    if not p or not auto.mode_on(conn):
        return False
    with db.transaction(conn):
        p = db.one(
            conn, "select * from content_projects where id=%s for update", (p["id"],)
        )
        try:
            invalidate(conn, p["id"], expected or p["current_script_version_id"])
        except NeedsReview:
            return False
        if auto._fix_in_progress(conn, p["id"]):
            return True
        count = auto.fix_attempts(conn, p["id"])
        if count >= auto.max_attempts(conn):
            return False
        failed = [r for r in records if r.get("status") in pipeline.repair.BAD]
        notes = "; ".join(
            f"{r['key']}: {r['status']}: {r.get('note','')}" for r in failed
        )
        db.run(
            conn,
            """insert into generation_jobs(job_type,project_id,idempotency_key,status,requested_by,input)
            values('regenerate_script',%s,%s,'queued','owner',%s) on conflict(idempotency_key) do nothing""",
            (
                p["id"],
                f"preflight-repair:{p['id']}:{p['current_script_version_id']}:{count+1}",
                db.j(
                    {
                        "auto_fix": True,
                        "expected_version": str(p["current_script_version_id"]),
                        "instructions": (notes or reason)[:1500],
                        "review_policy": "recovery_v2",
                    }
                ),
            ),
        )
        db.audit(
            conn,
            "final_check_repair_queued",
            "project",
            p["id"],
            {
                "version": str(p["current_script_version_id"]),
                "claims": failed,
                "reason": reason,
            },
        )
    return True


def repair(conn, router, storage, job):
    from . import auto

    if not auto.mode_on(conn):
        raise NeedsReview("Auto Review & Post is off; automatic repair stopped")
    pid, inp = job["project_id"], job["input"] or {}
    with db.run_lock(conn, f"repair:{pid}") as free:
        if not free:
            raise NeedsReview("Another repair is already running")
        with db.transaction(conn):
            p = invalidate(
                conn, pid, inp.get("resume_version") or inp.get("expected_version")
            )
        sv = db.one(
            conn,
            "select * from script_versions where id=%s",
            (p["current_script_version_id"],),
        )
        if not sv:
            raise NeedsReview(
                "Package has no saved script; regenerate it from a researched idea"
            )
        script = Script.model_validate(sv["body"])
        facts = produce.saved_facts(conn, pid, script)
        if not facts or not facts.facts:
            raise NeedsReview("No saved evidence for targeted repair")
        sources = produce._sources_for(
            conn, list({f.source_id for f in facts.facts if f.source_id})
        )
        if inp.get("resume_version"):
            from types import SimpleNamespace

            report = p["quality_report"] or {}
            result = SimpleNamespace(
                script=script,
                facts=facts,
                report=report,
                issues=[
                    f["text"]
                    for f in report.get("findings", [])
                    if f.get("kind") == "blocker"
                ],
            )
            new = sv
        else:
            result = pipeline.finish_long(
                router,
                p["channel_slug"],
                script,
                facts,
                sources,
                set((p["quality_report"] or {}).get("writers") or []),
                [],
                reuse_editors=True,
                notes=[
                    inp.get("instructions")
                    or "Repair unsupported claims and remove repetition"
                ],
            )
            if not auto.mode_on(conn):
                raise NeedsReview("Automatic mode was switched off during repair")
            with db.transaction(conn):
                invalidate(conn, pid, sv["id"])
                new = produce.save_script(
                    conn,
                    pid,
                    result.script.model_dump(),
                    "rewrite",
                    result.trail,
                    result.claims,
                    result.facts,
                    sources,
                )
                db.run(
                    conn,
                    "update generation_jobs set input=jsonb_set(input,'{resume_version}',%s) where id=%s",
                    (db.j(str(new["id"])), job["id"]),
                )
                db.run(
                    conn,
                    "update content_projects set quality_report=%s,status='rendering',title=%s where id=%s",
                    (db.j(result.report), result.script.title, pid),
                )
        pkg, problems, trail = pipeline.make_package(
            router, p["channel_slug"], result.script, result.facts
        )
        pkg.youtube_description = produce.fill_sources(
            pkg.youtube_description, produce.sources_used(conn, pid)
        )
        from .. import offers

        pkg.youtube_description, offer = offers.add_to_description(
            conn, p["channel_slug"], pkg.youtube_description, result.script.full_text()
        )
        pdata = pkg.model_dump()
        if offer:
            pdata["affiliate_offer"] = offer
        current = db.one(
            conn,
            "select current_script_version_id from content_projects where id=%s",
            (pid,),
        )
        if str(current["current_script_version_id"]) != str(
            new["id"]
        ) or not auto.mode_on(conn):
            raise NeedsReview("Package or automation switch changed during repair")
        qr = {**result.report, "package_problems": problems}
        qr["writers"] = sorted(
            set(qr.get("writers") or []) | set(trail.get("companies") or [])
        )
        qr["findings"] = qr.get("findings", []) + [
            {**f, "code": "package_part"} for f in pipeline.package_findings(problems)
        ]
        db.run(
            conn,
            "update content_projects set recipe=coalesce(recipe,'{}'::jsonb)||%s,quality_report=%s where id=%s",
            (db.j({"package": pdata}), db.j(qr), pid),
        )
        db.run(
            conn,
            "update generation_jobs set input=jsonb_set(input,'{recovery_stage}',%s) where id=%s",
            (db.j("rendering"), job["id"]),
        )
        # Retire old derivatives; their words and media must not survive a changed parent script.
        old = db.all_(
            conn,
            "select id from content_projects where parent_project_id=%s and status not in ('rejected','archived')",
            (pid,),
        )
        oldids = [x["id"] for x in old]
        if oldids:
            db.run(
                conn,
                "update content_projects set status='rejected',approved_script_version_id=null where id=any(%s)",
                (oldids,),
            )
            db.run(
                conn,
                "update content_variants set status='rejected' where project_id=any(%s)",
                (oldids,),
            )
            db.run(
                conn,
                "update scheduled_posts set status='cancelled' where variant_id in(select id from content_variants where project_id=any(%s))",
                (oldids,),
            )
        children = []
        for n, short in enumerate(pkg.shorts):
            c = produce.ensure_project(
                conn,
                p["channel_slug"],
                "short",
                short.title,
                p["batch_week"],
                parent_id=pid,
                key=f"repair:{job['id']}:short:{n}",
            )
            produce.save_script(conn, c["id"], short.model_dump(), "rewrite", [trail])
            db.run(
                conn,
                "update content_projects set status='rendering',fresh_until=%s,quality_report=%s where id=%s",
                (
                    p["fresh_until"],
                    db.j({"issues": [], "writers": trail.get("companies", [])}),
                    c["id"],
                ),
            )
            produce.render_preview(
                conn, storage, c["id"], short.model_dump(), p["channel_slug"], "short"
            )
            produce.final_status(conn, c["id"])
            children.append(str(c["id"]))
        produce.render_preview(
            conn, storage, pid, result.script.model_dump(), p["channel_slug"], "long"
        )
        produce.make_thumbnails(conn, storage, pid, p["channel_slug"])
        if str(
            db.one(
                conn,
                "select current_script_version_id from content_projects where id=%s",
                (pid,),
            )["current_script_version_id"]
        ) != str(new["id"]):
            raise NeedsReview(
                "Package changed while rendering; do not approve these assets"
            )
        produce.final_status(conn, pid)
        current = db.one(conn, "select * from content_projects where id=%s", (pid,))
        for v in db.all_(
            conn,
            "select v.*,a.platform from content_variants v join social_accounts a on a.id=v.social_account_id where project_id=%s",
            (pid,),
        ):
            title, body, tags, hashtags = produce.variant_text(current, v, v["kind"])
            from ..publish import limits

            issues = limits.problems(
                v["platform"], v["kind"], title, body, tags, hashtags
            )
            asset = db.one(
                conn,
                "select id from media_assets where project_id=%s and kind='preview_video' order by created_at desc limit 1",
                (pid,),
            )
            db.run(
                conn,
                "update content_variants set title=%s,body=%s,tags=%s,hashtags=%s,preview_asset_id=%s,status=%s where id=%s",
                (
                    title,
                    body,
                    tags,
                    hashtags,
                    asset["id"] if asset else None,
                    (
                        "ready_for_review"
                        if not issues and current["status"] == "ready_for_review"
                        else "needs_attention"
                    ),
                    v["id"],
                ),
            )
        produce.plan_project_distribution(conn, pid)
        db.audit(
            conn,
            "automatic_repair_completed",
            "project",
            pid,
            {
                "from_version": str(sv["id"]),
                "version": str(new["id"]),
                "children": children,
            },
        )
        return {
            "version": str(new["id"]),
            "children": children,
            "issues": result.issues,
        }
