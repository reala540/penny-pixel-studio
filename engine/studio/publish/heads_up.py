"""A daily heads-up: the posts due in the next 24 hours, and for each one whether it will go out by itself.

It only reads. It runs the same checks the publisher runs at posting time (approval, version, pause, launch date,
connection, budget) so a problem is found the day before, not at the moment of posting. Nothing is sent, changed
or retried here.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from .. import db, links, notify
from .adapters import ADAPTERS, URL_RE, Capability
from .runner import _context, safety_problems, unclear_attempt

READY, ONE_TAP, NEEDS_YOU = "ready", "one_tap", "needs_you"

_PLAIN = {  # the publisher's reasons, said as what to do
    "paused": "publishing is paused: turn it back on in Settings, or it waits",
    "account disabled": "this account is turned off in Settings → Accounts",
    "variant not approved": "not approved yet: approve it in Review",
    "no explicit approval record": "not approved yet: approve it in Review",
    "the script changed after approval: approve the current version again":
        "the script changed after you approved it: approve the current version in Review",
    "content expired: time-sensitive facts must be rechecked":
        "its facts will be out of date by then: recheck it in Review",
    "media without license record": "a picture has no licence record: replace it in Review",
}


def _plain(problem: str) -> str:
    if problem.startswith("package is "):
        return f"the package is {problem.split()[2].replace('_', ' ')}, not approved: approve it in Review"
    return _PLAIN.get(problem, problem)


def check_post(conn, post: dict, adapters: dict, now: datetime) -> tuple[str, str]:
    """(state, what happens) for one scheduled post, judged as of its posting time."""
    at = post["scheduled_at"]
    ctx = _context(conn, post)
    if ctx is None:
        return NEEDS_YOU, "its post text is missing: remove it from the calendar"
    tz = db.get_setting(conn, "timezone", "Africa/Nairobi")
    if db.one(conn, """select 1 from channel_profiles where slug=%s and launch_date is not null
                       and launch_date > (%s at time zone %s)::date""", (ctx["channel_slug"], at, tz)):
        return NEEDS_YOU, "the channel's launch date is later, so it won't go out: change the launch date in Settings"
    problems = safety_problems(conn, post, ctx, at)
    if problems:
        return NEEDS_YOU, "; ".join(dict.fromkeys(_plain(p) for p in problems))
    if unclear_attempt(conn, post["id"]):
        return NEEDS_YOU, "an earlier try didn't finish clearly: check the platform, then record it or press Try again"
    adapter = adapters.get(ctx["platform"])
    if adapter is None:
        return NEEDS_YOU, f"{ctx['platform']} can't be posted to by the studio"
    acc = {"id": ctx["social_account_id"], "platform": ctx["platform"], "label": ctx["account_label"]}
    if ctx["platform"] == "x":
        text = (ctx.get("body") or "").strip()
        if not text or len(text) > 280:
            return NEEDS_YOU, "the post must be 1–280 characters: edit it in Review"
        if URL_RE.search(text):
            return NEEDS_YOU, "it contains a link, which is blocked to protect the X budget: edit it in Review"
    cap = adapter.capability(conn, acc, ctx["kind"])
    if cap.reason == "X monthly budget used up" and (at.year, at.month) != (now.year, now.month):
        cap = Capability(True, "api")  # a new month's budget starts before this post
    if not cap.can_publish:
        return NEEDS_YOU, f"{cap.reason}: connect it in Setup, or you'll get a copy-and-paste task at posting time"
    if cap.method == "api_draft":
        where = "make it Public in YouTube Studio" if ctx["platform"] == "youtube" else "finish it in the app"
        return ONE_TAP, f"uploads by itself as a draft, then {where}"
    if ctx["kind"] != "text_post" and not ((ctx["recipe"] or {}).get("render")):
        return NEEDS_YOU, "the video has nothing to render from: rebuild it in Review"
    note = " (X credits are checked by X when it posts)" if ctx["platform"] == "x" else ""
    return READY, f"will post by itself{note}"


_ICON = {READY: "✅", ONE_TAP: "👆", NEEDS_YOU: "⚠️"}


def build(conn, now: datetime | None = None, hours: int = 24, adapters: dict | None = None) -> dict | None:
    """The heads-up message for the posts in the next `hours`, or None when nothing is due."""
    now = now or datetime.now(timezone.utc)
    posts = db.all_(conn, """select sp.* from scheduled_posts sp where sp.status='scheduled'
                             and sp.scheduled_at >= %s and sp.scheduled_at < %s order by sp.scheduled_at""",
                    (now, now + timedelta(hours=hours)))
    if not posts:
        return None
    own = adapters is None
    adapters = adapters or {k: v() for k, v in ADAPTERS.items()}
    try:
        zone = ZoneInfo(db.get_setting(conn, "timezone", "Africa/Nairobi"))
        lines, counts = [], {READY: 0, ONE_TAP: 0, NEEDS_YOU: 0}
        for post in posts:
            state, what = check_post(conn, post, adapters, now)
            counts[state] += 1
            ctx = _context(conn, post) or {}
            title = (ctx.get("title") or ctx.get("project_title") or "Untitled").strip()
            title = title if len(title) <= 50 else title[:49] + "…"
            when = post["scheduled_at"].astimezone(zone).strftime("%a %d %b %H:%M")
            lines.append(f"{_ICON[state]} {when} · {ctx.get('account_label', '?')} · {title}\n    {what}")
    finally:
        if own:
            for a in adapters.values():
                getattr(a, "client", None) and a.client.close()
    n = len(posts)
    parts = [f"{counts[READY]} ready"] + ([f"{counts[ONE_TAP]} need one tap"] if counts[ONE_TAP] else []) \
        + ([f"{counts[NEEDS_YOU]} need you"] if counts[NEEDS_YOU] else [])
    return {"title": f"Next 24 hours: {n} post{'s' if n != 1 else ''} · " + ", ".join(parts),
            "body": "\n".join(lines) + f"\n\nTimes are {zone.key.replace('_', ' ')} time.",
            "needs_you": counts[NEEDS_YOU] > 0, "counts": counts}


def send(conn, now: datetime | None = None, adapters: dict | None = None) -> dict | None:
    """Send today's heads-up once (a rerun on the same day doesn't send it again)."""
    now = now or datetime.now(timezone.utc)
    msg = build(conn, now, adapters=adapters)
    if msg is None:
        return None
    day = now.astimezone(ZoneInfo(db.get_setting(conn, "timezone", "Africa/Nairobi"))).date()
    kind = "posts_need_you" if msg["needs_you"] else "posts_ready"
    notify.send(conn, kind, msg["title"], msg["body"], link=links.calendar(),
                dedupe_key=f"heads_up:{day}")
    return msg
