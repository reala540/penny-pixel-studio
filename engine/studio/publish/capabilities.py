"""What each connected account can really do right now, checked by the engine once a day and shown in Settings →
Accounts. A saved login or a requested permission isn't proof that posting works, so each line says what was checked.
Read-only: nothing here posts, approves or spends anything."""

from __future__ import annotations

from datetime import datetime, timezone

from .. import db
from .adapters import ADAPTERS

# what each platform needs from the owner's login to post (the names the platforms use)
NEEDED = {
    "youtube": ["https://www.googleapis.com/auth/youtube.upload"],
    "facebook": ["pages_show_list", "pages_read_engagement", "pages_manage_posts"],
    "tiktok": ["video.upload"],
    "x": ["tweet.write"],
}
MAIN_KIND = {"youtube": "long_video", "facebook": "reel", "tiktok": "short_video", "x": "text_post"}


def snapshot(conn, adapters: dict | None = None) -> dict:
    adapters = adapters or {k: v() for k, v in ADAPTERS.items()}
    out: dict = {"checked_at": datetime.now(timezone.utc).isoformat(), "accounts": {}}
    for acc in db.all_(conn, """select a.*, c.status conn_status, c.scopes, c.last_error, c.connected_at
                                from social_accounts a left join oauth_connections c on c.social_account_id = a.id"""):
        platform = acc["platform"]
        missing = [s for s in NEEDED.get(platform, []) if s not in (acc["scopes"] or [])]
        try:
            cap = adapters[platform].capability(conn, acc, MAIN_KIND[platform])
            can, method, reason = cap.can_publish, cap.method, cap.reason
        except Exception as exc:  # noqa: BLE001
            can, method, reason = False, "manual", f"Couldn't check: {type(exc).__name__}"
        ok = db.one(conn, """select max(coalesce(verified_at, published_at)) at from published_posts where social_account_id=%s""",
                    (acc["id"],))
        bad = db.one(conn, """select updated_at at, last_error from scheduled_posts where social_account_id=%s
                              and status in ('failed','needs_manual','needs_review') and last_error is not null
                              order by updated_at desc limit 1""", (acc["id"],))
        connected = acc["conn_status"] == "connected"
        if not connected:
            next_step = "Press Connect and sign in."
        elif missing:
            next_step = "Press Reconnect and allow every permission it asks for."
        elif not can:
            next_step = reason or "Check the settings for this platform."
        elif method == "api_draft":
            next_step = reason or "Posts arrive as drafts: finish them in the platform's app."
        else:
            next_step = ""
        out["accounts"][str(acc["id"])] = {
            "login_saved": connected, "connected_at": acc["connected_at"].isoformat() if acc["connected_at"] else None,
            "permissions_missing": missing, "can_publish": bool(can and connected and not missing),
            "method": method, "limitation": reason or "",
            "last_success_at": ok["at"].isoformat() if ok and ok["at"] else None,
            "last_problem": (bad["last_error"] or "")[:300] if bad else None,
            "last_problem_at": bad["at"].isoformat() if bad else None,
            "next_step": next_step,
        }
    db.set_setting(conn, "account_capabilities", out)
    return out
