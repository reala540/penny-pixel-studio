"""The owner's "Full auto-posting" switch: settings.publish_without_checks = {"on": true, "auto_approve": true}.

While it is on, every finished package (and its Shorts) is approved for the owner and its posts go out at their times
without the last-minute checks (publish/runner.py checks_off). Switching it off on the dashboard stops both: packages
wait for the owner again and the checks apply from the next run.

Approving here is exactly what the owner's Approve button does (approvals for the current script version, project and
posts approved, the database trigger schedules the posts), recorded as the owner's decision with a note naming the
switch. Packages still being made or repaired are left until their work finishes. Rejected, archived and already-sent
content is never touched. Accounts, licences, the publishing pause and duplicate protection still apply.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from .. import db

NOTE = "Approved automatically: the owner's Full auto-posting switch is on"
READY = ("ready_for_review", "needs_attention")


def full_auto(conn, now: datetime | None = None) -> bool:
    from ..publish.runner import checks_off

    v = db.get_setting(conn, "publish_without_checks", None)
    return isinstance(v, dict) and v.get("auto_approve") is True and checks_off(conn, now)


def _busy(conn, ids) -> bool:
    """Something is still making or repairing this package (a queued fix is cancelled instead: see approve_ready)."""
    return bool(db.one(conn, """select 1 from generation_jobs where project_id = any(%s)
                                 and (status in ('running','retrying') or (status='queued' and job_type <> 'regenerate_script'))
                                 limit 1""", (ids,)))


def approve_ready(conn, now: datetime | None = None) -> dict:
    """Approve every finished package and restart its held posts. Does nothing while the switch is off."""
    now = now or datetime.now(timezone.utc)
    if not full_auto(conn, now):
        return {}
    from .auto import move_missed_slots

    approved, restarted = [], 0
    heads = db.all_(conn, """select id from content_projects where parent_project_id is null and status = any(%s)
                             order by created_at""", (list(READY),))
    for h in heads:
        family = db.all_(conn, """select id from content_projects where (id=%s or parent_project_id=%s)
                                   and status not in ('rejected','archived')""", (h["id"], h["id"]))
        ids = [f["id"] for f in family]
        if _busy(conn, ids):
            continue
        with db.transaction(conn):
            locked = db.all_(conn, """select id, status, current_script_version_id from content_projects where id = any(%s)
                                       order by parent_project_id nulls first, id for update""", (ids,))
            if not full_auto(conn, now) or next((r for r in locked if r["id"] == h["id"]), {}).get("status") not in READY:
                continue  # switched off, or the owner decided, while we were looking
            # a queued automatic rewrite would withdraw this approval: the owner chose to post as it is
            db.run(conn, """update generation_jobs set status='cancelled', cancel_requested_at=now(), finished_at=now(),
                            error_message='Cancelled: Full auto-posting approved this package as it is'
                            where project_id = any(%s) and status='queued' and job_type='regenerate_script'""", (ids,))
            todo = [r for r in locked if r["status"] in READY]
            for r in todo:
                db.run(conn, """insert into approvals (target_type, target_id, decision, script_version_id, notes, source)
                                values ('project', %s, 'approved', %s, %s, 'owner')""", (r["id"], r["current_script_version_id"], NOTE))
            db.run(conn, """update content_projects set status='approved', approved_script_version_id=current_script_version_id
                            where id = any(%s)""", ([r["id"] for r in todo],))
            variants = db.all_(conn, """select id from content_variants where project_id = any(%s) and status = any(%s)""",
                               ([r["id"] for r in todo], list(READY)))
            for v in variants:
                db.run(conn, """insert into approvals (target_type, target_id, decision, notes, source)
                                values ('variant', %s, 'approved', %s, 'owner')""", (v["id"], NOTE))
                db.run(conn, "update content_variants set status='approved' where id=%s", (v["id"],))
            move_missed_slots(conn, [v["id"] for v in variants], now)
        approved.append(str(h["id"]))
    restarted = restart_held(conn, now)
    if approved or restarted:
        db.audit(conn, "full_auto_posting", "settings", "publish_without_checks",
                 {"approved": approved, "posts_restarted": restarted})
    return {"approved": approved, "posts_restarted": restarted}


def restart_held(conn, now: datetime) -> int:
    """Posts of approved packages that a last-minute check stopped (never sent) go back on the schedule; any whose
    time has passed move to the account's next free slot."""
    from .auto import move_missed_slots

    with db.transaction(conn):
        rows = db.all_(conn, """
            update scheduled_posts sp set status='scheduled', last_error=null, locked_until=null
              from content_variants v join content_projects p on p.id=v.project_id
             where v.id=sp.variant_id and sp.status in ('blocked','needs_review','pending_approval')
               and v.status='approved' and p.status='approved' and sp.scheduled_at > %s
               and not exists (select 1 from publish_attempts pa where pa.scheduled_post_id=sp.id)
               and not exists (select 1 from published_posts pp where pp.scheduled_post_id=sp.id)
            returning sp.variant_id""", (now - timedelta(days=4),))
        if rows:
            move_missed_slots(conn, list({r["variant_id"] for r in rows}), now)
    return len(rows)
