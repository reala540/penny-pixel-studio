import json
import os
import re
import uuid
from pathlib import Path

import psycopg
import pytest

from studio import db

ROOT = Path(__file__).resolve().parents[2]
ADMIN_URL = os.environ.get("STUDIO_TEST_ADMIN_URL", "postgresql://postgres:postgres@localhost:5432/postgres")


def _admin():
    return psycopg.connect(ADMIN_URL, autocommit=True)


@pytest.fixture(scope="session")
def db_url():
    name = f"studio_test_{uuid.uuid4().hex[:8]}"
    try:
        with _admin() as c:
            c.execute(f"create database {name}")
    except psycopg.OperationalError:
        pytest.skip("PostgreSQL not available (set STUDIO_TEST_ADMIN_URL)")
    url = ADMIN_URL.rsplit("/", 1)[0] + f"/{name}"
    with psycopg.connect(url, autocommit=True) as c:
        c.execute((ROOT / "engine/tests/sql/supabase_stub.sql").read_text())
        for f in sorted((ROOT / "supabase/migrations").glob("*.sql")):
            c.execute(f.read_text())
    yield url
    with _admin() as c:
        c.execute(f"drop database if exists {name} with (force)")


@pytest.fixture(autouse=True)
def offline_research(monkeypatch):
    """Tests never go to the network, and the small sample sources make fewer facts than a real idea needs."""
    from studio.research import deepen
    from studio.script import pipeline

    monkeypatch.setattr(deepen, "fetcher", lambda: None)
    monkeypatch.setattr(pipeline, "MIN_LONG_FACTS", 3)
    monkeypatch.setattr(pipeline, "SHORT_SECTION", 0)  # sample sections are short on purpose: renders stay quick


TABLES_KEEP = {"schema_migrations"}


@pytest.fixture()
def conn(db_url, tmp_path, monkeypatch):
    monkeypatch.setenv("STUDIO_WORK_DIR", str(tmp_path / "work"))
    monkeypatch.setenv("TOKEN_ENCRYPTION_KEY", "MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY=")
    for k in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY"):
        monkeypatch.delenv(k, raising=False)
    c = db.connect(db_url)
    tables = [r["tablename"] for r in db.all_(c, "select tablename from pg_tables where schemaname='public'")]
    # throwaway test database: switch the permanence triggers off only for this wipe between tests
    c.execute("set session_replication_role = replica")
    c.execute("truncate " + ", ".join(f"public.{t}" for t in tables) + " restart identity cascade")
    c.execute("set session_replication_role = origin")
    c.execute("delete from storage.objects")
    yield c
    c.close()


@pytest.fixture()
def synced(conn):
    from studio import produce

    produce.sync_config(conn)
    db.run(conn, "update channel_profiles set launch_date = null")  # tests set launch dates themselves
    return conn
