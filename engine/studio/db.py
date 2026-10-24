"""Thin PostgreSQL helpers (psycopg 3). The engine connects with the DB owner role."""

from __future__ import annotations

import json
import os
import re
from contextlib import contextmanager
from typing import Any, Iterator

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb


_DIRECT = re.compile(r"^(postgres(?:ql)?://)([^:@/]+)(:[^@]*)?@db\.([a-z0-9]+)\.supabase\.co(?::\d+)?(/[^?]*)?(\?.*)?$")


def candidate_urls(url: str, region: str | None) -> list[str]:
    """Supabase's direct address is IPv6-only, which GitHub runners can't reach. Try the Session pooler first."""
    m = _DIRECT.match(url.strip())
    if not m or not region:
        return [url]
    scheme, user, pw, ref, path, query = m.groups()
    user = user if "." in user else f"{user}.{ref}"
    tail = f"{path or '/postgres'}{query or ''}"
    pooled = [f"{scheme}{user}{pw or ''}@aws-{n}-{region}.pooler.supabase.com:5432{tail}" for n in (0, 1)]
    return pooled + [url]


def _region() -> str | None:
    from . import config

    return os.environ.get("SUPABASE_REGION") or (config.services().get("quotas", {}).get("supabase", {}).get("region"))


def connect(url: str) -> psycopg.Connection:
    # prepare_threshold=None keeps us compatible with Supabase's transaction pooler.
    urls = candidate_urls(url, _region()) if "supabase.co" in url else [url]
    last: Exception | None = None
    for u in urls:
        try:
            return psycopg.connect(u, row_factory=dict_row, autocommit=True, prepare_threshold=None, connect_timeout=15)
        except psycopg.OperationalError as e:
            last = e
            # A wrong password is the same everywhere: stop instead of hiding it behind later attempts.
            if "password authentication failed" in str(e).lower():
                raise
    assert last is not None
    raise last


@contextmanager
def transaction(conn: psycopg.Connection) -> Iterator[psycopg.Connection]:
    with conn.transaction():
        yield conn


def j(value: Any) -> Jsonb:
    return Jsonb(value)


def one(conn: psycopg.Connection, sql: str, params: Any = None) -> dict | None:
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchone() if cur.description else None


def all_(conn: psycopg.Connection, sql: str, params: Any = None) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchall() if cur.description else []


def run(conn: psycopg.Connection, sql: str, params: Any = None) -> int:
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return cur.rowcount


def audit(conn: psycopg.Connection, action: str, target_type: str | None = None,
          target_id: Any = None, details: dict | None = None, actor: str = "engine") -> None:
    run(conn,
        "insert into audit_logs (actor, action, target_type, target_id, details) values (%s,%s,%s,%s,%s)",
        (actor, action, target_type, str(target_id) if target_id else None, j(details or {})))


def get_setting(conn: psycopg.Connection, key: str, default: Any = None) -> Any:
    row = one(conn, "select value from settings where key = %s", (key,))
    return row["value"] if row else default


def set_setting(conn: psycopg.Connection, key: str, value: Any) -> None:
    run(conn, """insert into settings (key, value) values (%s, %s)
                 on conflict (key) do update set value = excluded.value""", (key, j(value)))


def dumps(value: Any) -> str:
    return json.dumps(value, default=str)
