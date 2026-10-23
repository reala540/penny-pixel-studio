"""Encrypted OAuth token storage + refresh. Shares the AES-256-GCM format with the Cloudflare Worker:
base64( 12-byte IV || ciphertext || 16-byte tag ), key = base64 of 32 random bytes (TOKEN_ENCRYPTION_KEY).
"""

from __future__ import annotations

import base64
import json
import os
import time

import httpx
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from . import config, db
from .errors import AuthError, TransientError


def _key() -> bytes:
    raw = config.runtime().token_key
    if not raw:
        raise AuthError("TOKEN_ENCRYPTION_KEY is not set")
    key = base64.b64decode(raw)
    if len(key) != 32:
        raise AuthError("TOKEN_ENCRYPTION_KEY must be 32 bytes, base64-encoded")
    return key


def encrypt(data: dict) -> str:
    iv = os.urandom(12)
    ct = AESGCM(_key()).encrypt(iv, json.dumps(data).encode(), None)
    return base64.b64encode(iv + ct).decode()


def decrypt(blob: str) -> dict:
    raw = base64.b64decode(blob)
    return json.loads(AESGCM(_key()).decrypt(raw[:12], raw[12:], None))


def load(conn, account_id) -> dict:
    row = db.one(conn, "select ciphertext from oauth_secrets where social_account_id=%s", (account_id,))
    if not row:
        raise AuthError("Account is not connected")
    return decrypt(row["ciphertext"])


def save(conn, account_id, tokens: dict) -> None:
    db.run(conn, """insert into oauth_secrets (social_account_id, ciphertext) values (%s,%s)
                    on conflict (social_account_id) do update set ciphertext=excluded.ciphertext, updated_at=now()""",
           (account_id, encrypt(tokens)))
    exp = tokens.get("expires_at")
    db.run(conn, """update oauth_connections set status='connected', last_checked_at=now(), last_error=null,
                    token_expires_at=to_timestamp(%s) where social_account_id=%s""",
           (exp if exp else None, account_id))


def mark_broken(conn, account_id, reason: str) -> None:
    db.run(conn, """update oauth_connections set status='needs_reauth', last_error=%s, last_checked_at=now()
                    where social_account_id=%s""", (reason[:500], account_id))


REFRESH = {
    "youtube": ("https://oauth2.googleapis.com/token", "GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "client_id"),
    "tiktok": ("https://open.tiktokapis.com/v2/oauth/token/", "TIKTOK_CLIENT_KEY", "TIKTOK_CLIENT_SECRET", "client_key"),
    "x": ("https://api.x.com/2/oauth2/token", "X_CLIENT_ID", "X_CLIENT_SECRET", "client_id"),
}


def access_token(conn, account: dict, client: httpx.Client | None = None) -> tuple[str, dict]:
    """Valid access token for an account, refreshing (and re-saving rotated refresh tokens) when needed."""
    tokens = load(conn, account["id"])
    platform = account["platform"]
    if platform == "facebook":
        if not tokens.get("page_token"):
            raise AuthError("Facebook Page token missing — reconnect the Page")
        return tokens["page_token"], tokens
    if tokens.get("access_token") and float(tokens.get("expires_at") or 0) > time.time() + 120:
        return tokens["access_token"], tokens
    if not tokens.get("refresh_token"):
        mark_broken(conn, account["id"], "No refresh token; reconnect")
        raise AuthError(f"{platform}: no refresh token")
    url, id_env, secret_env, id_field = REFRESH[platform]
    data = {"grant_type": "refresh_token", "refresh_token": tokens["refresh_token"], id_field: os.environ.get(id_env, "")}
    secret = os.environ.get(secret_env, "")
    auth = None
    if platform == "x" and secret:
        auth = (os.environ.get(id_env, ""), secret)  # confidential client uses HTTP basic auth
    elif secret:
        data["client_secret"] = secret
    try:
        r = (client or httpx.Client(timeout=30)).post(url, data=data, auth=auth)
    except httpx.HTTPError as exc:
        raise TransientError(f"{platform}: token refresh network error") from exc
    if r.status_code >= 500:
        raise TransientError(f"{platform}: token endpoint error {r.status_code}")
    body = r.json() if r.content else {}
    if r.status_code >= 400 or "access_token" not in body:
        reason = body.get("error_description") or body.get("error") or f"HTTP {r.status_code}"
        mark_broken(conn, account["id"], f"Token refresh failed: {reason}")
        raise AuthError(f"{platform}: token refresh failed ({reason}) — reconnect in Settings")
    tokens["access_token"] = body["access_token"]
    tokens["expires_at"] = time.time() + int(body.get("expires_in", 3600))
    if body.get("refresh_token"):
        tokens["refresh_token"] = body["refresh_token"]  # X and TikTok rotate refresh tokens
    save(conn, account["id"], tokens)
    return tokens["access_token"], tokens


def check_health(conn) -> list[dict]:
    """Refresh every connected account once so broken tokens are found before publish time."""
    report = []
    for acc in db.all_(conn, """select a.* from social_accounts a join oauth_connections c on c.social_account_id=a.id
                                where c.status in ('connected','expired') and a.enabled"""):
        try:
            access_token(conn, acc)
            report.append({"account": acc["label"], "ok": True})
        except AuthError as exc:
            report.append({"account": acc["label"], "ok": False, "error": str(exc)})
        except TransientError as exc:
            report.append({"account": acc["label"], "ok": None, "error": str(exc)})
    return report
