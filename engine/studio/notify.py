"""Persistent Telegram delivery. Deduplicate events, retry failed deliveries, never block content work."""
from __future__ import annotations

import html
import re
from functools import lru_cache

import httpx

from . import config, db

MAX_ATTEMPTS = 5

# Updates that don't need the owner. With the "important" preference they stay in the app only; problems and
# anything that needs a decision always go to Telegram.
ROUTINE = {"ideas_ready", "research_ready", "published", "auto_approved", "auto_fixing", "provider_check_ready",
           "ai_model_back", "job_cancelled", "auto_replace"}
GROUPED = {"job_failed", "publish_blocked", "ai_key_rejected"}   # identical repeats within 30 minutes are sent once

_SECRETS = [
    (re.compile(r"(?i)\b(api[_-]?key|key|token|access_token|refresh_token|secret|password|passwd|client_secret|sig|signature)=([^&\s'\"]+)"), r"\1=[hidden]"),
    (re.compile(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9._~+/=-]{8,}"), r"\1 [hidden]"),
    (re.compile(r"\bbot\d{5,}:[A-Za-z0-9_-]{20,}"), "bot[hidden]"),
    (re.compile(r"\b(sk|pk|rk|gsk|xai|hf|ghp|gho|github_pat|sb_secret)[-_][A-Za-z0-9_-]{12,}"), "[hidden key]"),
    (re.compile(r"\bAIza[0-9A-Za-z_-]{20,}"), "[hidden key]"),
    (re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{5,}"), "[hidden token]"),
]


def scrub(text: str | None) -> str:
    """Remove anything that looks like a key, token or password before it's stored or sent."""
    out = text or ""
    for pattern, repl in _SECRETS:
        out = pattern.sub(repl, out)
    return out


@lru_cache(maxsize=64)
def _supported(conn) -> bool:
    return bool(db.one(conn, """select 1 from information_schema.columns where table_schema='public'
                               and table_name='notifications' and column_name='delivery_attempts'"""))


def _hold(conn, row: dict, reason: str) -> bool:
    """Kept in the app, deliberately not sent to Telegram (never retried)."""
    if _supported(conn):
        db.run(conn, "update notifications set error=%s, delivery_attempts=%s where id=%s", (reason, MAX_ATTEMPTS, row["id"]))
    else:
        db.run(conn, "update notifications set error=%s where id=%s", (reason, row["id"]))
    return False


def _deliver(conn, row: dict, client=None) -> bool:
    rt = config.runtime()
    chat = rt.telegram_chat_id or db.get_setting(conn, "telegram_chat_id")
    if not rt.telegram_token or not chat:
        db.run(conn, "update notifications set error='telegram not configured' where id=%s", (row["id"],))
        return False
    if row["kind"] in ROUTINE and db.get_setting(conn, "telegram_alerts", "all") == "important":
        return _hold(conn, row, "Not sent to Telegram: routine updates are off (Settings → Notifications)")
    supported = _supported(conn)
    if supported:
        row = db.one(conn, """update notifications set delivery_attempts=delivery_attempts+1,
                   delivery_locked_until=now()+interval '2 minutes'
                   where id=%s and sent_at is null and delivery_attempts < %s
                     and (next_delivery_at is null or next_delivery_at <= now())
                     and (delivery_locked_until is null or delivery_locked_until < now()) returning *""",
                     (row["id"], MAX_ATTEMPTS))
        if not row:
            return False
    text = f"<b>{html.escape(row['title'][:300])}</b>"
    anchor = ""
    link = row.get("link") or ""
    escaped_link = html.escape(link, quote=True)
    if link.startswith(("https://", "http://")) and len(escaped_link) <= 1000:
        anchor = f'\n<a href="{escaped_link}">Open dashboard</a>'
    if row.get("body"):
        # Escaping can expand one character to six; never truncate in the middle of an HTML entity.
        budget = max(0, (3900 - len(text) - len(anchor) - 1) // 6)
        text += "\n" + html.escape(row["body"][:min(1800, budget)])
    text += anchor
    delay, ok, error = 60, False, None
    try:
        def post(c):
            return c.post(f"https://api.telegram.org/bot{rt.telegram_token}/sendMessage", json={
                "chat_id": chat, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True})
        if client is None:
            with httpx.Client(timeout=20) as c:
                response = post(c)
        else:
            response = post(client)
        body = response.json()
        ok = response.status_code == 200 and body.get("ok") is True
        if not ok:
            # Never store a request URL or provider body: they may contain secrets.
            error = f"Telegram delivery failed (HTTP {response.status_code})"
            delay = max(60, min(int((body.get("parameters") or {}).get("retry_after", 60)), 21600))
    except (httpx.HTTPError, ValueError, TypeError):
        error = "Telegram delivery unconfirmed; a retry may deliver a duplicate."
    if supported:
        attempts = row["delivery_attempts"]
        delay = max(delay, min(60 * 2 ** (attempts - 1), 21600))
        db.run(conn, """update notifications set sent_at=case when %s then now() else sent_at end, error=%s,
                 delivery_locked_until=null, next_delivery_at=now()+make_interval(secs => %s) where id=%s""",
               (ok, None if ok else error, delay, row["id"]))
    else:  # rolling deployment: keep the previous schema working until migration 13 is applied
        db.run(conn, "update notifications set sent_at=case when %s then now() else sent_at end,error=%s where id=%s",
               (ok, None if ok else error, row["id"]))
    return ok


def send(conn, kind: str, title: str, body: str = "", link: str | None = None,
         dedupe_key: str | None = None, client=None) -> bool:
    """Record the event (once per dedupe_key) and try to deliver it. Delivery failures never undo the work."""
    title, body = scrub(title)[:300], scrub(body)
    row = db.one(conn, """insert into notifications(kind,title,body,link,dedupe_key) values(%s,%s,%s,%s,%s)
                       on conflict(dedupe_key) do nothing returning *""", (kind, title, body, link, dedupe_key))
    if row is None and dedupe_key:
        row = db.one(conn, "select * from notifications where dedupe_key=%s and sent_at is null", (dedupe_key,))
    elif row is not None and kind in GROUPED and db.one(conn, """
            select 1 from notifications where kind=%s and body=%s and id<>%s and sent_at > now() - interval '30 minutes'
            limit 1""", (kind, body, row["id"])):
        return _hold(conn, row, "Not sent to Telegram again: the same problem was reported in the last 30 minutes")
    return _deliver(conn, row, client) if row else False


def retry_pending(conn, client=None, limit: int = 20) -> int:
    if not _supported(conn):
        return 0
    rt = config.runtime()
    if not rt.telegram_token or not (rt.telegram_chat_id or db.get_setting(conn, "telegram_chat_id")):
        return 0
    rows = db.all_(conn, """select * from notifications where sent_at is null and delivery_attempts < %s
                         and next_delivery_at<=now()
                         and (delivery_locked_until is null or delivery_locked_until<now())
                         order by created_at limit %s""", (MAX_ATTEMPTS, limit))
    return sum(_deliver(conn, row, client) for row in rows)
