"""Migration 14 audit fixes: who may Stop & clear, version-exact approval, approval withdrawn by a new script,
published text kept, least-privilege table grants, and the publisher/auto-review version checks."""
import uuid

import psycopg
import pytest

from studio import db
from studio.publish import runner
from .test_database import as_user, reset_role

OWNER = str(uuid.uuid4())


def _package(c, status="ready_for_review"):
    acc = db.one(c, "select id from social_accounts limit 1")["id"]
    p = db.one(c, "insert into content_projects (channel_slug, format, title, status) values ('ai','long','t',%s) returning id",
               (status,))["id"]
    v1 = db.one(c, "insert into script_versions (project_id, version, origin, body) values (%s,1,'ai','{}') returning id", (p,))["id"]
    db.run(c, "update content_projects set current_script_version_id=%s where id=%s", (v1, p))
    var = db.one(c, """insert into content_variants (project_id, social_account_id, kind, status, body)
                       values (%s,%s,'text_post','ready_for_review','hello') returning id""", (p, acc))["id"]
    db.run(c, """insert into scheduled_posts (variant_id, social_account_id, scheduled_at, idempotency_key, status)
                 values (%s,%s,now() + interval '2 days',%s,'pending_approval')""", (var, acc, f"k-{p}"))
    return p, v1, var


def _claim_owner(c):
    as_user(c, OWNER)
    assert db.one(c, "select claim_ownership() ok")["ok"]
    reset_role(c)


def test_stop_and_clear_refuses_any_signed_in_account_and_still_works_for_the_engine(synced):
    c = synced
    _claim_owner(c)
    for who in (OWNER, str(uuid.uuid4())):  # not even the owner may call it directly: the Worker does, after its own check
        as_user(c, who)
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            c.execute("select public.stop_and_clear()")
        reset_role(c)
    c.execute("set role anon")
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        c.execute("select public.stop_and_clear()")
    reset_role(c)
    # the Worker's service-role token
    c.execute("set role service_role")
    c.execute("select set_config('request.jwt.claims', '{\"role\":\"service_role\"}', false)")
    assert db.one(c, "select public.stop_and_clear() r")["r"]["reason"] == "nothing is running"
    c.execute("select set_config('request.jwt.claims', '', false)")
    reset_role(c)
    # the engine's own database session
    assert db.one(c, "select public.stop_and_clear() r")["r"]["reason"] == "nothing is running"


def test_approval_is_for_the_exact_reviewed_version(synced):
    c = synced
    _claim_owner(c)
    p, v1, var = _package(c)
    v2 = db.one(c, "insert into script_versions (project_id, version, origin, body) values (%s,2,'ai','{}') returning id", (p,))["id"]
    db.run(c, "update content_projects set current_script_version_id=%s where id=%s", (v2, p))
    as_user(c, OWNER)
    with pytest.raises(psycopg.Error, match="script changed"):
        c.execute("select approve_project(%s, null, %s)", (p, v1))   # the owner reviewed v1; v2 is current
    with pytest.raises(psycopg.Error, match="script changed"):
        c.execute("select approve_project(%s)", (p,))                # no version: refused, never approved unseen
    assert db.one(c, "select approve_project(%s, null, %s) n", (p, v2))["n"] == 1
    reset_role(c)
    head = db.one(c, "select status, approved_script_version_id from content_projects where id=%s", (p,))
    assert head["status"] == "approved" and head["approved_script_version_id"] == v2
    assert db.one(c, "select status from scheduled_posts where variant_id=%s", (var,))["status"] == "scheduled"
    # deciding twice records nothing new
    as_user(c, OWNER)
    with pytest.raises(psycopg.Error, match="no longer waiting"):
        c.execute("select approve_project(%s, null, %s)", (p, v2))
    reset_role(c)
    assert db.one(c, "select count(*) n from approvals where target_type='project' and target_id=%s", (p,))["n"] == 1


def test_new_script_withdraws_approval_and_published_script_is_kept(synced):
    c = synced
    _claim_owner(c)
    p, v1, var = _package(c)
    as_user(c, OWNER)
    db.one(c, "select approve_project(%s, null, %s)", (p, v1))
    reset_role(c)
    v2 = db.one(c, "insert into script_versions (project_id, version, origin, body) values (%s,2,'owner_edit','{}') returning id",
                (p,))["id"]
    db.run(c, "update content_projects set current_script_version_id=%s, status='rendering' where id=%s", (v2, p))
    assert db.one(c, "select approved_script_version_id a from content_projects where id=%s", (p,))["a"] is None
    assert db.one(c, "select status from content_variants where id=%s", (var,))["status"] == "ready_for_review"
    assert db.one(c, "select status from scheduled_posts where variant_id=%s", (var,))["status"] == "pending_approval"
    assert db.one(c, "select count(*) n from audit_logs where action='approval_withdrawn'")["n"] == 1
    db.run(c, "update content_projects set status='published' where id=%s", (p,))
    v3 = db.one(c, "insert into script_versions (project_id, version, origin, body) values (%s,3,'owner_edit','{}') returning id",
                (p,))["id"]
    with pytest.raises(psycopg.Error, match="already published"):
        c.execute("update content_projects set current_script_version_id=%s where id=%s", (v3, p))


def test_published_post_text_cannot_change(synced):
    c = synced
    p, _, var = _package(c)
    db.run(c, "update content_variants set status='published' where id=%s", (var,))
    with pytest.raises(psycopg.Error, match="already published"):
        c.execute("update content_variants set body='rewritten' where id=%s", (var,))


def test_api_roles_have_no_truncate_trigger_or_references(synced):
    c = synced
    rows = db.all_(c, """select table_name, grantee, privilege_type from information_schema.role_table_grants
                         where table_schema='public' and grantee in ('anon','authenticated')
                           and privilege_type in ('TRUNCATE','TRIGGER','REFERENCES')""")
    assert rows == []


def test_publisher_blocks_content_changed_after_approval(synced):
    c = synced
    p, v1, var = _package(c)
    db.run(c, "update content_projects set status='approved', approved_script_version_id=current_script_version_id where id=%s", (p,))
    db.run(c, "update content_variants set status='approved' where id=%s", (var,))
    db.run(c, "insert into approvals (target_type, target_id, decision, decided_by) values ('project',%s,'approved',%s)", (p, OWNER))
    post = db.one(c, "select * from scheduled_posts where variant_id=%s", (var,))
    ctx = runner._context(c, post)
    assert not [x for x in runner.safety_problems(c, post, ctx, post["scheduled_at"]) if "script" in x or "package is" in x]
    # a version change that bypassed the trigger (e.g. restored data) is still caught by the publisher
    v2 = db.one(c, "insert into script_versions (project_id, version, origin, body) values (%s,2,'ai','{}') returning id", (p,))["id"]
    c.execute("alter table content_projects disable trigger content_projects_withdraw_approval")
    db.run(c, "update content_projects set current_script_version_id=%s where id=%s", (v2, p))
    c.execute("alter table content_projects enable trigger content_projects_withdraw_approval")
    ctx = runner._context(c, post)
    assert "the script changed after approval: approve the current version again" in runner.safety_problems(c, post, ctx, post["scheduled_at"])
    db.run(c, "update content_projects set status='rendering' where id=%s", (p,))
    ctx = runner._context(c, post)
    assert "package is rendering, not approved" in runner.safety_problems(c, post, ctx, post["scheduled_at"])


def test_auto_review_does_not_approve_a_script_changed_during_review(synced, monkeypatch):
    from datetime import datetime, timezone
    from studio.review import auto
    c = synced
    p, v1, var = _package(c)
    family = auto._family(c, p)              # what the reviewer looked at (v1)
    variants = auto._variants(c, [p])
    v2 = db.one(c, "insert into script_versions (project_id, version, origin, body) values (%s,2,'owner_edit','{}') returning id",
                (p,))["id"]
    db.run(c, "update content_projects set current_script_version_id=%s where id=%s", (v2, p))  # the owner edits meanwhile
    monkeypatch.setattr(auto, "mode_on", lambda conn: True)
    assert auto._approve(c, family, variants, "ok", datetime.now(timezone.utc)) == -1
    assert db.one(c, "select status from content_projects where id=%s", (p,))["status"] == "ready_for_review"
    assert db.one(c, "select count(*) n from approvals where target_id=%s", (p,))["n"] == 0


def _retrying_stage(c, project_id, *, due=True, attempts=1, max_attempts=3):
    return db.one(c, """insert into generation_jobs (job_type, idempotency_key, project_id, status, attempts, max_attempts,
                                                     next_attempt_at, requested_by)
                        values ('script', %s, %s, 'retrying', %s, %s, now() + %s * interval '1 hour', 'system') returning id""",
                  (f"script:{project_id}:{uuid.uuid4()}", project_id, attempts, max_attempts, -1 if due else 1))["id"]


def test_due_retries_really_run_with_the_attempts_left(synced, monkeypatch):
    from studio import produce
    c = synced
    idea = db.one(c, """insert into content_ideas (channel_slug, title, status, batch_week)
                        values ('ai','An idea','selected', current_date) returning id""")["id"]
    p = db.one(c, "insert into content_projects (channel_slug, format, title, status, idea_id) values ('ai','long','t','failed',%s) returning id",
               (idea,))["id"]
    calls = []
    monkeypatch.setattr(produce, "produce_idea", lambda conn, router, storage, **kw: calls.append(kw) or {"status": "ready_for_review"})
    # not due yet, or no attempts left: nothing runs
    j = _retrying_stage(c, p, due=False)
    assert produce.resume_due_retries(c, None, None) == [] and calls == []
    db.run(c, "update generation_jobs set next_attempt_at = now() - interval '1 minute', attempts = 3 where id=%s", (j,))
    assert produce.resume_due_retries(c, None, None) == []
    # due with attempts left: resumes this package without giving the steps fresh attempts
    db.run(c, "update generation_jobs set attempts = 1 where id=%s", (j,))
    assert produce.resume_due_retries(c, None, None) == [{"project_id": str(p), "status": "ready_for_review"}]
    assert calls == [{"content_idea_id": idea, "fresh_attempts": False}]
    # the owner has a request running for it, or already decided it: left alone
    calls.clear()
    owner_job = db.one(c, """insert into generation_jobs (job_type, idempotency_key, project_id, status, requested_by)
                             values ('regenerate_script', 'o1', %s, 'running', 'owner') returning id""", (p,))["id"]
    assert produce.resume_due_retries(c, None, None) == [] and calls == []
    db.run(c, "update generation_jobs set status='completed' where id=%s", (owner_job,))
    db.run(c, "update content_projects set status='approved' where id=%s", (p,))
    assert produce.resume_due_retries(c, None, None) == [] and calls == []


def test_last_failed_retry_tells_the_owner_once(synced, monkeypatch):
    from studio import notify, produce
    c = synced
    idea = db.one(c, "insert into content_ideas (channel_slug, title, status, batch_week) values ('ai','I','selected', current_date) returning id")["id"]
    p = db.one(c, "insert into content_projects (channel_slug, format, title, status, idea_id) values ('ai','long','Prompts','failed',%s) returning id",
               (idea,))["id"]
    j = _retrying_stage(c, p, attempts=2)
    sent = []
    monkeypatch.setattr(notify, "send", lambda conn, kind, title, body="", **kw: sent.append((kind, title, kw.get("dedupe_key"))))

    def last_attempt_fails(conn, router, storage, **kw):
        db.run(conn, "update generation_jobs set status='failed', attempts=3 where id=%s", (j,))
        raise RuntimeError("All providers failed for 'scriptwriter'")
    monkeypatch.setattr(produce, "produce_idea", last_attempt_fails)
    out = produce.resume_due_retries(c, None, None)
    assert out[0]["status"] == "retrying" and "providers failed" in out[0]["error"]
    assert sent == [("job_failed", "Stopped retrying: Prompts", f"retries_exhausted:{p}")]


def test_automatic_retry_keeps_remaining_attempts(synced, monkeypatch):
    from studio import produce
    c = synced
    idea = db.one(c, "insert into content_ideas (channel_slug, title, status, batch_week) values ('ai','I','selected', current_date) returning id")["id"]
    p = db.one(c, "insert into content_projects (channel_slug, format, title, status, idea_id) values ('ai','long','t','failed',%s) returning id",
               (idea,))["id"]
    j = _retrying_stage(c, p, attempts=2)
    monkeypatch.setattr(produce, "produce_project", lambda *a, **k: {"status": "retrying"})
    monkeypatch.setattr(produce, "idea_for_production", lambda conn, **kw: db.one(conn, "select * from content_ideas where id=%s", (idea,)))
    with pytest.raises(RuntimeError):
        produce.produce_idea(c, None, None, content_idea_id=idea, fresh_attempts=False)
    assert db.one(c, "select attempts, status from generation_jobs where id=%s", (j,)) == {"attempts": 2, "status": "retrying"}
    with pytest.raises(RuntimeError):
        produce.produce_idea(c, None, None, content_idea_id=idea)   # the owner's Try again gives fresh attempts
    assert db.one(c, "select attempts, status from generation_jobs where id=%s", (j,)) == {"attempts": 0, "status": "pending"}


def test_owner_cannot_move_a_post_into_the_past_or_onto_another_by_any_path(synced):
    c = synced
    _claim_owner(c)
    p, v1, var = _package(c)
    post = db.one(c, "select id, social_account_id from scheduled_posts where variant_id=%s", (var,))
    var2 = db.one(c, """insert into content_variants (project_id, social_account_id, kind, status, body)
                        values (%s,%s,'text_post','ready_for_review','second') returning id""", (p, post["social_account_id"]))["id"]
    other = db.one(c, """insert into scheduled_posts (variant_id, social_account_id, scheduled_at, idempotency_key, status)
                         values (%s,%s,now() + interval '5 days','k-other','pending_approval') returning scheduled_at""",
                   (var2, post["social_account_id"]))
    as_user(c, OWNER)
    with pytest.raises(psycopg.Error, match="future time"):
        c.execute("update scheduled_posts set scheduled_at = now() - interval '1 hour' where id=%s", (post["id"],))
    with pytest.raises(psycopg.Error, match="within 30 minutes"):
        c.execute("update scheduled_posts set scheduled_at = %s + interval '10 minutes' where id=%s", (other["scheduled_at"], post["id"]))
    c.execute("update scheduled_posts set scheduled_at = now() + interval '3 days' where id=%s", (post["id"],))
    # a schedule function moving several posts passes through brief overlaps: only its own checks apply
    c.execute("select set_config('request.path', '/rpc/save_posting_schedule', false)")
    c.execute("update scheduled_posts set scheduled_at = %s + interval '10 minutes' where id=%s", (other["scheduled_at"], post["id"]))
    with pytest.raises(psycopg.Error, match="future time"):
        c.execute("update scheduled_posts set scheduled_at = now() - interval '1 hour' where id=%s", (post["id"],))
    c.execute("select set_config('request.path', '', false)")
    reset_role(c)
    c.execute("select set_config('request.jwt.claim.sub', '', false), set_config('request.jwt.claims', '', false)")
    # the engine (its own session, no sign-in) plans and repairs slots itself
    db.run(c, "update scheduled_posts set scheduled_at = now() - interval '1 minute' where id=%s", (post["id"],))
