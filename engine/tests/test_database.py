"""Migrations, Row Level Security, immutability, budget enforcement and the job runner."""

import uuid

import psycopg
import pytest

from studio import budget, db, jobs
from studio.errors import AuthError, BudgetExceeded, TransientError

OWNER = str(uuid.uuid4())
STRANGER = str(uuid.uuid4())


def as_user(conn, uid, email="owner@example.com"):
    conn.execute("set role authenticated")
    conn.execute("select set_config('request.jwt.claim.sub', %s, false)", (uid,))
    conn.execute("select set_config('request.jwt.claims', %s, false)", (f'{{"email":"{email}"}}',))


def reset_role(conn):
    conn.execute("reset role")


def test_owner_claim_once_and_rls(synced):
    c = synced
    as_user(c, OWNER)
    assert db.one(c, "select public.claim_ownership() ok")["ok"] is True
    assert len(db.all_(c, "select * from social_accounts")) == 5
    reset_role(c)
    as_user(c, STRANGER, "intruder@example.com")
    assert db.one(c, "select public.claim_ownership() ok")["ok"] is False  # already claimed
    assert db.all_(c, "select * from social_accounts") == []
    assert db.all_(c, "select * from settings") == []
    reset_role(c)
    c.execute("set role anon")
    assert db.all_(c, "select * from content_projects") == []
    reset_role(c)


def test_owner_cannot_read_secrets_or_fake_publish(synced):
    c = synced
    acc = db.one(c, "select id from social_accounts limit 1")["id"]
    db.run(c, "insert into oauth_secrets (social_account_id, ciphertext) values (%s, 'x')", (acc,))
    as_user(c, OWNER)
    db.one(c, "select public.claim_ownership()")
    assert db.all_(c, "select * from oauth_secrets") == []
    reset_role(c)
    p = db.one(c, "insert into content_projects (channel_slug, format, title) values ('ai','long','t') returning id")
    v = db.one(c, "insert into content_variants (project_id, social_account_id, kind) values (%s,%s,'text_post') returning id",
               (p["id"], acc))
    sp = db.one(c, "insert into scheduled_posts (variant_id, social_account_id, scheduled_at, idempotency_key) "
                   "values (%s,%s,now(),'k1') returning id", (v["id"], acc))
    as_user(c, OWNER)
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        c.execute("update scheduled_posts set status='published' where id=%s", (sp["id"],))
    reset_role(c)
    as_user(c, OWNER)
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        c.execute("update budgets set monthly_cap_usd=50 where service='x_api'")
    reset_role(c)
    as_user(c, OWNER)
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        c.execute("select public.reserve_budget('x_api', 0.01, 'sneaky')")
    reset_role(c)


def test_approval_moves_schedule_via_trigger(synced):
    c = synced
    acc = db.one(c, "select id from social_accounts limit 1")["id"]
    p = db.one(c, "insert into content_projects (channel_slug, format, title) values ('ai','long','t') returning id")
    v = db.one(c, "insert into content_variants (project_id, social_account_id, kind) values (%s,%s,'text_post') returning id",
               (p["id"], acc))
    db.run(c, "insert into scheduled_posts (variant_id, social_account_id, scheduled_at, idempotency_key) values (%s,%s,now(),'k')",
           (v["id"], acc))
    db.run(c, "update content_variants set status='approved' where id=%s", (v["id"],))
    assert db.one(c, "select status from scheduled_posts")["status"] == "scheduled"
    db.run(c, "update content_variants set status='rejected' where id=%s", (v["id"],))
    assert db.one(c, "select status from scheduled_posts")["status"] == "cancelled"


def test_script_versions_are_immutable(synced):
    c = synced
    p = db.one(c, "insert into content_projects (channel_slug, format, title) values ('ai','long','t') returning id")
    sv = db.one(c, "insert into script_versions (project_id, version, origin, body) values (%s,1,'ai','{}') returning id",
                (p["id"],))
    with pytest.raises(psycopg.errors.RaiseException):
        c.execute("update script_versions set hook='changed' where id=%s", (sv["id"],))


def test_budget_hard_cap_and_idempotency(synced):
    c = synced
    for i in range(66):  # 66 * 0.015 = 0.99
        budget.reserve(c, "x_api", 0.015, f"ref-{i}")
    budget.reserve(c, "x_api", 0.015, "ref-0")  # same reference is idempotent, no extra spend
    with pytest.raises(BudgetExceeded):
        budget.reserve(c, "x_api", 0.015, "ref-new")
    budget.release(c, "ref-1")
    budget.reserve(c, "x_api", 0.015, "ref-new")
    s = budget.month_summary(c, "x_api")
    assert s["cap"] == 1.0 and s["remaining"] < 0.015


def test_job_runner_idempotent_retry_and_block(synced):
    c = synced
    calls = {"n": 0}

    def ok(_):
        calls["n"] += 1
        return {"value": 42}

    r1 = jobs.run_stage(c, "t", "job-ok", ok)
    r2 = jobs.run_stage(c, "t", "job-ok", ok)
    assert r1.ok and r2.output == {"value": 42} and calls["n"] == 1

    def flaky(_):
        raise TransientError("network blip")

    r = jobs.run_stage(c, "t", "job-flaky", flaky)
    assert r.status == "retrying" and r.job["next_attempt_at"] is not None
    assert db.one(c, "select count(*) n from job_attempts where job_id=%s", (r.job["id"],))["n"] == 1

    def auth(_):
        raise AuthError("bad key")

    assert jobs.run_stage(c, "t", "job-auth", auth).status == "blocked"


def test_control_room_activity_indexes_exist(conn):
    rows = db.all_(conn, "select indexname from pg_indexes where schemaname='public'")
    names = {r["indexname"] for r in rows}
    assert {"provider_usage_created_idx", "provider_usage_job_created_idx", "generation_jobs_updated_idx"} <= names


def test_stale_running_jobs_resume(synced):
    c = synced
    j = jobs.ensure_job(c, "render", "stale")
    db.run(c, "update generation_jobs set status='running', started_at=now() - interval '5 hours' where id=%s", (j["id"],))
    assert jobs.reset_stale_running(c) == 1
    assert db.one(c, "select status from generation_jobs where id=%s", (j["id"],))["status"] == "retrying"


def test_batch_runs_never_overlap(db_url, conn):
    other = db.connect(db_url)
    try:
        with db.run_lock(conn, "production") as first:
            assert first is True
            with db.run_lock(other, "production") as second:
                assert second is False  # a mission and the Sunday batch can't produce at the same time
            with db.run_lock(other, "research") as research:
                assert research is True  # different kinds don't block each other
        with db.run_lock(other, "production") as again:
            assert again is True  # released when the first run ends
    finally:
        other.close()
