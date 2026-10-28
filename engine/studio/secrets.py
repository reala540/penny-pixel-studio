"""Secrets saved on the dashboard Setup page.

They are stored encrypted in `app_secrets` (same AES-256-GCM format as social logins). At start-up the engine
loads them into its environment, so every module keeps reading `os.environ` as before. A value saved in the
dashboard wins over the GitHub secret of the same name; GitHub secrets still work when nothing is saved.
"""

from __future__ import annotations

import os

from . import db

MANAGED = (
    "TELEGRAM_BOT_TOKEN", "TELEGRAM_WEBHOOK_SECRET",
    "GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "FACEBOOK_APP_ID", "FACEBOOK_APP_SECRET",
    "TIKTOK_CLIENT_KEY", "TIKTOK_CLIENT_SECRET", "X_CLIENT_ID", "X_CLIENT_SECRET",
    "YOUTUBE_API_KEY", "PEXELS_API_KEY", "PIXABAY_API_KEY", "FRED_API_KEY", "SEC_USER_AGENT", "FREESOUND_API_KEY",
)
_original = {name: bool(os.environ.get(name)) for name in MANAGED}  # before anything below changes os.environ


def apply_saved(conn) -> dict:
    """Load dashboard-saved secrets into os.environ. Returns {"loaded": [...], "unreadable": [...]} (names only)."""
    out: dict = {"loaded": [], "unreadable": []}
    if db.one(conn, "select to_regclass('public.app_secrets') t")["t"] is None:
        return out  # database not migrated yet
    from . import oauth

    record_presence(conn)
    for row in db.all_(conn, "select name, ciphertext from app_secrets where name = any(%s)", (list(MANAGED),)):
        try:
            value = str(oauth.decrypt(row["ciphertext"]).get("value") or "")
        except Exception:  # wrong TOKEN_ENCRYPTION_KEY or damaged value: keep the GitHub secret, report it
            out["unreadable"].append(row["name"])
            continue
        if value:
            os.environ[row["name"]] = value
            out["loaded"].append(row["name"])
    return out


def record_presence(conn) -> None:
    """Tell the Setup page which of these exist as GitHub secrets (true/false only, never values)."""
    if os.environ.get("GITHUB_ACTIONS") != "true":
        return  # a local run says nothing about the GitHub secrets
    present = dict(_original)
    db.run(conn, """insert into settings (key, value) values ('engine_env_presence', %s)
                    on conflict (key) do update set value = excluded.value, updated_at = now()""",
           (db.j({"names": present, "checked_at": db.one(conn, "select now() t")["t"].isoformat()}),))
