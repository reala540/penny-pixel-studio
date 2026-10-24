"""v2.5: posting schedule editor, dashboard-saved secrets and live job progress."""

import os
import uuid
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import psycopg
import pytest

from studio import db, jobs, oauth, secrets

from .test_database import as_user, reset_role
from .test_end_to_end import _produce_week, silent_tts  # noqa: F401  (fixture)

OWNER = str(uuid.uuid4())


def owner(c):
    as_user(c, OWNER)
    db.one(c, "select public.claim_ownership() ok")


def account(c, label):
    return db.one(c, "select * from social_accounts where label=%s", (label,))


def test_owner_edits_a_schedule_and_it_is_validated_and_audited(synced):
    c = synced
    acc = account(c, "TikTok")
    owner(c)
    out = db.one(c, """select public.set_posting_schedule(%s, %s) r""",
                 (acc["id"], db.j({"posting_days": ["sun", "MON", "mon"], "posting_times": ["21:15", "07:00"],
                                   "targets": {"short_video": 5}, "enabled": False})))["r"]
    assert out["weekly_targets"]["posting_days"] == ["mon", "sun"]
    assert out["weekly_targets"]["posting_times"] == ["07:00", "21:15"]
    assert out["weekly_targets"]["short_video"] == 5
    for bad in ({"posting_days": ["funday"]}, {"posting_times": ["25:00"]}, {"targets": {"long_video": 2}},
                {"targets": {"short_video": 40}}, {"shorts_days": ["mon"]},
                {"posting_times": ["01:00", "02:00", "03:00", "04:00", "05:00"]}):
        with pytest.raises(psycopg.errors.RaiseException):
            db.one(c, "select public.set_posting_schedule(%s, %s) r", (acc["id"], db.j(bad)))
    reset_role(c)
    row = account(c, "TikTok")
    assert row["enabled"] is False and row["weekly_targets"]["short_video"] == 5
    log = db.one(c, "select actor, details from audit_logs where action='posting_schedule_changed'")
    assert log["actor"] == "owner" and log["details"]["before"]["posting_days"] == ["tue", "thu", "sun"]
    # someone else can't change it
    as_user(c, str(uuid.uuid4()), "intruder@example.com")
    with pytest.raises(psycopg.errors.RaiseException):
        db.one(c, "select public.set_posting_schedule(%s, %s) r", (acc["id"], db.j({"posting_days": ["mon"]})))
    reset_role(c)


def test_a_new_schedule_can_move_waiting_posts(synced, monkeypatch, silent_tts):
    c = synced
    _produce_week(c, monkeypatch)
    acc = account(c, "X")
    before = db.all_(c, "select id from scheduled_posts where social_account_id=%s order by scheduled_at", (acc["id"],))
    assert before
    owner(c)
    r = db.one(c, "select public.set_posting_schedule(%s, %s, true) r",
               (acc["id"], db.j({"posting_days": ["sat"], "posting_times": ["10:45"]})))["r"]
    reset_role(c)
    assert r["moved_posts"] == len(before)
    rows = db.all_(c, "select scheduled_at from scheduled_posts where social_account_id=%s order by scheduled_at", (acc["id"],))
    local = [x["scheduled_at"].astimezone(ZoneInfo("Africa/Nairobi")) for x in rows]
    assert all(t.strftime("%a %H:%M") == "Sat 10:45" for t in local)
    assert len({t for t in local}) == len(local) and all(x["scheduled_at"] > datetime.now(timezone.utc) for x in rows)


def test_config_sync_keeps_the_dashboard_schedule_and_stores_defaults(synced):
    from studio import produce

    c = synced
    acc = account(c, "X")
    owner(c)
    db.one(c, "select public.set_posting_schedule(%s, %s) r", (acc["id"], db.j({"posting_times": ["06:30"]})))
    reset_role(c)
    produce.sync_config(c)
    assert account(c, "X")["weekly_targets"]["posting_times"] == ["06:30"]
    assert db.get_setting(c, "posting_schedule_defaults")["X"]["posting_times"] == ["08:30"]


def test_dashboard_saved_secrets_win_and_bad_ones_are_reported(synced, monkeypatch):
    c = synced
    monkeypatch.setenv("YOUTUBE_API_KEY", "from-github")
    monkeypatch.delenv("PEXELS_API_KEY", raising=False)
    db.run(c, "insert into app_secrets (name, ciphertext, hint) values ('YOUTUBE_API_KEY', %s, 'hb12')",
           (oauth.encrypt({"value": "from-dashboard"}),))
    db.run(c, "insert into app_secrets (name, ciphertext) values ('PEXELS_API_KEY', 'not-a-real-ciphertext')")
    out = secrets.apply_saved(c)
    assert out == {"loaded": ["YOUTUBE_API_KEY"], "unreadable": ["PEXELS_API_KEY"]}
    assert os.environ["YOUTUBE_API_KEY"] == "from-dashboard"
    assert "PEXELS_API_KEY" not in os.environ
    with pytest.raises(psycopg.errors.CheckViolation):
        db.run(c, "insert into app_secrets (name, ciphertext) values ('SUPABASE_DB_URL', 'x')")


def test_presence_is_recorded_only_in_github_actions_and_never_values(synced, monkeypatch):
    c = synced
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    secrets.record_presence(c)
    assert db.get_setting(c, "engine_env_presence") is None
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setitem(secrets._original, "YOUTUBE_API_KEY", True)
    secrets.record_presence(c)
    names = db.get_setting(c, "engine_env_presence")["names"]
    assert names["YOUTUBE_API_KEY"] is True and set(names.values()) <= {True, False}


def test_no_client_can_read_saved_secrets(synced):
    c = synced
    db.run(c, "insert into app_secrets (name, ciphertext) values ('FRED_API_KEY', 'x')")
    owner(c)
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        db.all_(c, "select * from app_secrets")
    reset_role(c)
    c.execute("set role anon")
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        db.all_(c, "select * from app_secrets")
    reset_role(c)


def test_progress_and_tracked_runs_show_what_is_running(synced):
    c = synced
    jobs.progress(c, "no job: ignored")   # outside a job nothing happens
    with jobs.tracked_run(c, "weekly_research", "weekly_research:test:1", {"week": "2026-10-19"}) as run:
        row = db.one(c, "select id, status, requested_by from generation_jobs where idempotency_key='weekly_research:test:1'")
        assert row["status"] == "running" and row["requested_by"] == "system"
        jobs.progress(c, "Collecting research", 1, 2)
        assert db.one(c, "select progress from generation_jobs where id=%s", (row["id"],))["progress"] == \
            {"label": "Collecting research", "step": 1, "total": 2}
        run["output"] = {"ideas": {"ai": 2}}
    done = db.one(c, "select status, progress, output from generation_jobs where id=%s", (row["id"],))
    assert done["status"] == "completed" and done["progress"] is None and done["output"] == {"ideas": {"ai": 2}}
    with pytest.raises(RuntimeError):
        with jobs.tracked_run(c, "weekly_production", "weekly_production:test:1"):
            raise RuntimeError("render failed")
    assert db.one(c, "select status, error_message from generation_jobs where idempotency_key='weekly_production:test:1'") == \
        {"status": "failed", "error_message": "render failed"}
    assert jobs.reset_stale_running(c, older_than_minutes=-1) == 0   # tracked runs are never "stale-reset"
