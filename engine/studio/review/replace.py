"""Held packages don't wait forever (Auto Review & Post).

When Smart Mode holds a package only because it is sensitive (news that dates, sensitive money topics, flagged
ideas, partly supported facts), the owner gets a reminder in the app and on Telegram. If they still haven't decided
after the replacement time, the studio makes a safer package from an evergreen, non-sensitive idea and, once that
exists, erases the held one. Limits keep this from looping or burning the free AI quota:

* only packages whose *one* failed check is Smart Mode (quality or policy problems always wait for a person);
* never during a trust period (a replacement would be held for the same reason);
* at most `max_per_week` replacements per channel;
* nothing published, approved or scheduled is ever touched.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from .. import config, db, notify
from ..ai.router import Router

DEFAULTS = {"enabled": True, "remind_after_hours": 12, "replace_after_hours": 24, "max_per_week": 2}
TRUST = "Trust period"


def settings(conn) -> dict:
    raw = db.get_setting(conn, "auto_replace", {}) or {}
    c = {**DEFAULTS, **{k: v for k, v in raw.items() if k in DEFAULTS}}
    c["enabled"] = c["enabled"] is True
    c["remind_after_hours"] = min(max(float(c["remind_after_hours"]), 1), 168)
    c["replace_after_hours"] = min(max(float(c["replace_after_hours"]), c["remind_after_hours"]), 336)
    c["max_per_week"] = min(max(int(c["max_per_week"]), 0), 7)
    return c


def held_for_risk(conn) -> list[dict]:
    """Packages waiting for the owner only because Smart Mode found them sensitive."""
    out = []
    for p in db.all_(conn, """select * from content_projects where parent_project_id is null and status='needs_attention'
                              order by updated_at"""):
        rv = db.one(conn, "select * from auto_reviews where project_id=%s order by created_at desc limit 1", (p["id"],))
        if not rv or rv["verdict"] != "needs_review":
            continue
        failed = [c for c in rv["checks"] or [] if not c.get("ok")]
        if not failed or any(c.get("code") != "smart_mode" for c in failed):
            continue
        reasons = [r.strip() for r in (failed[0].get("detail") or "").split(";") if r.strip()]
        out.append({"project": p, "review_id": rv["id"], "since": rv["created_at"], "reasons": reasons,
                    "replaceable": bool(reasons) and not any(r.startswith(TRUST) for r in reasons)})
    return out


def replaced_this_week(conn, channel: str, now: datetime) -> int:
    return db.one(conn, """select count(*) n from auto_replacements where channel_slug=%s and outcome='replaced'
                           and created_at > %s""", (channel, now - timedelta(days=7)))["n"]


def safe_idea(conn, channel: str, avoid: set[str]) -> dict | None:
    """The best unused idea that Smart Mode would let post by itself: evergreen, not sensitive, with sources."""
    from .auto import MONEY_SENSITIVE

    rows = db.all_(conn, """select * from generated_ideas g
                            where g.channel_slug in (%s, 'both') and g.status in ('new','saved') and g.content_idea_id is null
                              and g.sensitivity = 'none' and (g.scores->>'evergreen')::boolean is true
                              and g.created_at > now() - interval '30 days' and jsonb_array_length(g.trend_signals) > 0
                            order by g.total desc, g.created_at desc limit 30""", (channel,))
    for g in rows:
        text = f"{g['title']} {g['summary']}"
        if g["title"].strip().lower() in avoid or (channel == "money" and MONEY_SENSITIVE.search(text)):
            continue
        return g
    return None


def _new_ideas(conn, router: Router, channel: str) -> None:
    from ..ideas import generator

    generator.run(conn, router, trigger="scheduled", overrides={"channels": [channel], "count": 6, "notify": False})


def erase(conn, storage, project_id) -> int:
    paths = db.one(conn, "select public.erase_projects(array[%s]::uuid[]) p", (project_id,))["p"] or []
    if paths:
        try:
            storage.delete(list(paths))
        except Exception:  # a leftover file is harmless; the records are gone
            pass
    return len(paths)


def replace(conn, router: Router, storage, h: dict) -> dict:
    from .. import produce

    p = h["project"]
    ch, link = p["channel_slug"], f"{config.runtime().dashboard_url}/content"
    avoid = {p["title"].strip().lower()}
    idea = safe_idea(conn, ch, avoid)
    if idea is None:
        _new_ideas(conn, router, ch)
        idea = safe_idea(conn, ch, avoid)
    if idea is None:
        db.run(conn, """insert into auto_replacements (channel_slug, old_title, reasons, outcome, detail)
                        values (%s,%s,%s,'failed','No safe idea found')""", (ch, p["title"], h["reasons"]))
        notify.send(conn, "auto_replace", f"Still waiting for you: {p['title']}",
                    "No safer idea was available to replace it, so it keeps waiting for your decision.",
                    link=link, dedupe_key=f"replace_none:{p['id']}")
        return {"outcome": "failed", "reason": "no safe idea"}
    try:
        made = produce.produce_idea(conn, router, storage, generated_idea_id=idea["id"], channel=ch)
    except Exception as exc:  # the held package stays: nothing is erased without a replacement
        db.run(conn, """insert into auto_replacements (channel_slug, old_title, reasons, new_title, outcome, detail)
                        values (%s,%s,%s,%s,'failed',%s)""", (ch, p["title"], h["reasons"], idea["title"], str(exc)[:500]))
        notify.send(conn, "auto_replace", f"Couldn't replace: {p['title']}",
                    f"Making the safer video failed ({str(exc)[:200]}). The original keeps waiting for you.",
                    link=link, dedupe_key=f"replace_fail:{p['id']}")
        return {"outcome": "failed", "reason": str(exc)[:200]}
    files = erase(conn, storage, p["id"])
    db.run(conn, "update generated_ideas set status='archived' where content_idea_id=%s", (p["idea_id"],))
    db.run(conn, """insert into auto_replacements (channel_slug, old_title, reasons, new_project_id, new_title, outcome, detail)
                    values (%s,%s,%s,%s,%s,'replaced',%s)""",
           (ch, p["title"], h["reasons"], made["project_id"], idea["title"], f"status {made['status']}, {files} files removed"))
    db.run(conn, "insert into audit_logs (actor, action, target_type, target_id, details) values ('engine','auto_replaced','project',%s,%s)",
           (str(p["id"]), db.j({"old_title": p["title"], "reasons": h["reasons"], "new_project": made["project_id"],
                                "new_title": idea["title"]})))
    notify.send(conn, "auto_replace", f"Replaced: {p['title']}",
                f"You didn't decide in time, so it was erased and replaced by a safer video: {idea['title']} "
                f"({'posts by itself' if made['status'] in ('approved', 'scheduled') else made['status'].replace('_', ' ')}).",
                link=link, dedupe_key=f"replaced:{p['id']}")
    return {"outcome": "replaced", "new_project_id": made["project_id"], "new_title": idea["title"]}


def tick(conn, router: Router, storage, now: datetime | None = None) -> dict:
    """Send due reminders, make due replacements, and note when the next one is due (the Worker wakes the engine)."""
    from . import auto

    now = now or datetime.now(timezone.utc)
    cfg = settings(conn)
    out: dict = {"reminded": 0, "replaced": [], "next_at": None}
    if not cfg["enabled"] or not auto.mode_on(conn):
        db.run(conn, "delete from settings where key='auto_replace_next_at'")
        return {**out, "skipped": True}
    remind, wait = timedelta(hours=cfg["remind_after_hours"]), timedelta(hours=cfg["replace_after_hours"])
    upcoming: list[datetime] = []
    for h in held_for_risk(conn):
        p, since = h["project"], h["since"]
        if now >= since + remind:
            later = (f"If you don't decide within {cfg['replace_after_hours'] - cfg['remind_after_hours']:.0f} more hours, "
                     "the studio erases it and makes a safer video instead." if h["replaceable"]
                     else "It waits for you: this channel is still in its trust period.")
            if notify.send(conn, "held_reminder", f"Waiting for you: {p['title']}",
                           f"Why: {'; '.join(h['reasons'])[:400]}. Approve or reject it in the app. {later}",
                           link=f"{config.runtime().dashboard_url}/content/{p['id']}",
                           dedupe_key=f"held_remind:{p['id']}:{h['review_id']}"):
                out["reminded"] += 1
        else:
            upcoming.append(since + remind)
        if not h["replaceable"]:
            continue
        if now < since + wait:
            upcoming.append(since + wait)
            continue
        if replaced_this_week(conn, p["channel_slug"], now) >= cfg["max_per_week"]:
            notify.send(conn, "auto_replace", f"Weekly replacement limit reached ({cfg['max_per_week']})",
                        f"'{p['title']}' keeps waiting for you. Change the limit in Settings → Auto Review & Post.",
                        dedupe_key=f"replace_limit:{p['channel_slug']}:{now.date().isocalendar()[1]}")
            continue
        out["replaced"].append({"old": p["title"], **replace(conn, router, storage, h)})
    out["next_at"] = min(upcoming).isoformat() if upcoming else None
    if out["next_at"]:
        db.set_setting(conn, "auto_replace_next_at", out["next_at"])
    else:
        db.run(conn, "delete from settings where key='auto_replace_next_at'")
    return out
