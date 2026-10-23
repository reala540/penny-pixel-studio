"""Thin PostgreSQL helpers (psycopg 3). The engine connects with the DB owner role."""

from __future__ import annotations

import json
from contextlib import contextmanager
from typing import Any, Iterator

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb


def connect(url: str) -> psycopg.Connection:
    # prepare_threshold=None keeps us compatible with Supabase's transaction pooler.
    return psycopg.connect(url, row_factory=dict_row, autocommit=True, prepare_threshold=None)


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
