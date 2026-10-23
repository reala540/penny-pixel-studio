"""Telegram notifications (deduplicated, never include secrets)."""

from __future__ import annotations

import html

import httpx

from . import config, db


def send(conn, kind: str, title: str, body: str = "", link: str | None = None, dedupe_key: str | None = None,
         client: httpx.Client | None = None) -> bool:
    row = db.one(conn, """insert into notifications (kind, title, body, link, dedupe_key)
                          values (%s,%s,%s,%s,%s) on conflict (dedupe_key) do nothing returning id""",
                 (kind, title, body, link, dedupe_key))
    if row is None:
        return False  # already sent
    rt = config.runtime()
    chat = rt.telegram_chat_id or db.get_setting(conn, "telegram_chat_id")
    if not rt.telegram_token or not chat:
        db.run(conn, "update notifications set error='telegram not configured' where id=%s", (row["id"],))
        return False
    text = f"<b>{html.escape(title)}</b>"
    if body:
        text += f"\n{html.escape(body)}"
    if link:
        text += f'\n<a href="{html.escape(link, quote=True)}">Open dashboard</a>'
    try:
        r = (client or httpx.Client(timeout=20)).post(
            f"https://api.telegram.org/bot{rt.telegram_token}/sendMessage",
            json={"chat_id": chat, "text": text[:4000], "parse_mode": "HTML", "disable_web_page_preview": True})
        ok = r.status_code == 200
        db.run(conn, "update notifications set sent_at=case when %s then now() end, error=%s where id=%s",
               (ok, None if ok else f"HTTP {r.status_code}", row["id"]))
        return ok
    except httpx.HTTPError as exc:
        db.run(conn, "update notifications set error=%s where id=%s", (str(exc)[:300], row["id"]))
        return False
