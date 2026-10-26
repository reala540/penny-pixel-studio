"""Owner isolation, scoped cancellation, queue identity and notification delivery recovery."""
import uuid
from datetime import datetime, timezone

import httpx
import psycopg
import pytest

from studio import db, jobs, maintenance, notify
from .test_database import as_user, reset_role


def owner(conn):
    as_user(conn, str(uuid.uuid4()))
    assert db.one(conn, 'select claim_ownership() ok')['ok']


def test_atomic_patches_and_clear_undo_preserve_unrelated_fields(synced):
    c = synced
    owner(c)
    def patch(key, value, expected=None):
        return db.one(c, 'select patch_studio_setting(%s,%s,%s) v', (key, db.j(value), db.j(expected) if expected else None))['v']
    patch('idea_generator', {'count': 12})
    assert patch('idea_generator', {'languages': ['fr']})['count'] == 12
    patch('ui_cleared', {'activity': 'A'})
    patch('ui_cleared', {'review_log': 'B'})
    assert patch('ui_cleared', {'activity': None}, {'activity': 'A'})['review_log'] == 'B'
    patch('ui_cleared', {'activity': 'C'})
    with pytest.raises(psycopg.Error, match='changed elsewhere'):
        patch('ui_cleared', {'activity': None}, {'activity': 'A'})
    reset_role(c)


def test_enqueue_deduplicates_and_cancel_affects_only_one_request(synced):
    c = synced
    owner(c)
    def enqueue(inp):
        return db.one(c, "select enqueue_owner_job('check_providers',null,%s) id", (db.j(inp),))['id']
    a = enqueue({'provider': 'groq'})
    assert enqueue({'provider': 'groq'}) == a
    b = enqueue({'provider': 'gemini'})
    assert db.one(c, 'select cancel_owner_job(%s) s', (a,))['s'] == 'cancelled'
    assert db.one(c, 'select status from generation_jobs where id=%s', (b,))['status'] == 'queued'
    assert enqueue({'provider': 'groq'}) != a  # explicit retry after cancellation is permitted
    reset_role(c)


def test_non_owner_cannot_call_reliability_functions(synced):
    c = synced
    owner(c)
    reset_role(c)
    as_user(c, str(uuid.uuid4()), 'other@example.com')
    with pytest.raises(psycopg.Error, match='owner only'):
        c.execute("select enqueue_owner_job('check_providers')")
    with pytest.raises(psycopg.Error, match='owner only'):
        c.execute("select patch_studio_setting('idea_generator','{}')")
    reset_role(c)


def test_queue_claims_one_at_a_time_and_cancellation_keeps_other_work(synced, monkeypatch):
    c = synced
    owner(c)
    a = db.one(c, "select enqueue_owner_job('check_providers',null,'{}') id")['id']
    b = db.one(c, "select enqueue_owner_job('check_providers',null,'{\"provider\":\"groq\"}') id")['id']
    reset_role(c)
    seen = []
    def run(conn, router, storage, job):
        seen.append(job['id'])
        if job['id'] == a:
            assert db.one(c, 'select status from generation_jobs where id=%s', (b,))['status'] == 'queued'
            db.run(c, 'update generation_jobs set cancel_requested_at=now() where id=%s', (a,))
            with jobs.job_context(uuid.uuid4()):  # a nested stage must still see its parent's cancellation
                jobs.check_stop(c)
        return {}
    monkeypatch.setattr(maintenance, '_run_owner_job', run)
    result = maintenance._process_round(c, None, None, 10)
    assert [x['status'] for x in result] == ['cancelled', 'completed']
    assert seen == [a, b]


def test_notification_retry_deduplicates_event_not_delivery(synced, monkeypatch):
    c = synced
    monkeypatch.setenv('TELEGRAM_BOT_TOKEN', 'test-not-a-real-token')
    monkeypatch.setenv('TELEGRAM_CHAT_ID', 'test-chat')
    calls = []
    def handler(req):
        calls.append(req)
        return httpx.Response(429, json={'ok': False, 'parameters': {'retry_after': 90}}) if len(calls) == 1 else httpx.Response(200, json={'ok': True})
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        assert not notify.send(c, 'test', 'Ready', dedupe_key='test-event', client=client)
        assert not notify.send(c, 'test', 'Ready', dedupe_key='test-event', client=client)  # backoff respected
        assert len(calls) == 1
        db.run(c, "update notifications set next_delivery_at=now()-interval '1 second'")
        assert notify.retry_pending(c, client=client) == 1
        assert not notify.send(c, 'test', 'Ready', dedupe_key='test-event', client=client)
    assert len(calls) == 2
    rows = db.all_(c, 'select * from notifications')
    assert len(rows) == 1 and rows[0]['sent_at'] and rows[0]['delivery_attempts'] == 2 and rows[0]['error'] is None


def test_delivery_attempts_are_bounded_and_do_not_store_token(synced, monkeypatch):
    c = synced
    monkeypatch.setenv('TELEGRAM_BOT_TOKEN', 'secret-test-token')
    monkeypatch.setenv('TELEGRAM_CHAT_ID', 'test-chat')
    def fail(req):
        raise httpx.ReadTimeout(f'url contains secret-test-token', request=req)
    with httpx.Client(transport=httpx.MockTransport(fail)) as client:
        for _ in range(8):
            notify.send(c, 'test', 'Ready', dedupe_key='bounded', client=client)
            db.run(c, "update notifications set next_delivery_at=now()-interval '1 second'")
    row = db.one(c, 'select * from notifications')
    assert row['delivery_attempts'] == 5 and 'secret-test-token' not in row['error']


def test_recent_progress_is_not_abandoned(synced):
    c = synced
    j = jobs.ensure_job(c, 'render', 'long-but-active')
    db.run(c, "update generation_jobs set status='running', started_at=now()-interval '8 hours',updated_at=now() where id=%s", (j['id'],))
    assert jobs.reset_stale_running(c) == 0


def test_cloud_drafts_use_revisions_and_owner_isolation(synced):
    c = synced
    owner(c)
    payload = {'id': 'draft-a', 'step': 'idea', 'channel': 'ai', 'own': 'A useful video topic'}
    def save(data, revision):
        return db.one(c, "select save_studio_draft('draft-a',%s,%s) v", (db.j(data) if data is not None else None, revision))['v']
    assert save(payload, 0)['revision'] == 1
    assert save({**payload,'own':'Another device'}, 0)['conflict']
    assert db.one(c, "select payload from studio_drafts where id='draft-a'")['payload'] == payload
    assert save(None, 1)['revision'] == 2
    assert db.one(c, "select payload from studio_drafts where id='draft-a'")['payload'] is None
    reset_role(c)
    as_user(c, str(uuid.uuid4()), 'stranger@example.com')
    assert db.all_(c, 'select * from studio_drafts') == []
    with pytest.raises(psycopg.Error, match='owner only'):
        save(payload, 2)
    reset_role(c)


def test_cloud_drafts_reject_credential_fields(synced):
    c = synced
    owner(c)
    with pytest.raises(psycopg.Error, match='Only creation choices'):
        db.one(c, "select save_studio_draft('bad',%s,0)", (db.j({'api_key':'not-for-a-draft'}),))
    assert db.one(c, 'select count(*) n from studio_drafts')['n'] == 0
    reset_role(c)


def test_activity_pages_do_not_drop_events_from_different_sources(synced):
    c=synced
    for i in range(160):
        db.run(c,"insert into notifications(kind,title,created_at) values('test',%s,now()-make_interval(secs=>%s))",(f'Event {i}',i))
    j=jobs.ensure_job(c,'run_research','old-research')
    db.run(c,"update generation_jobs set status='completed',finished_at=now()-interval '1 day' where id=%s",(j['id'],))
    owner(c)
    first=db.all_(c,'select * from studio_activity(0,150)')
    second=db.all_(c,'select * from studio_activity(150,150)')
    ids=lambda rows:{(x['kind'],str(x['record']['id'])) for x in rows}
    assert len(first)==150 and len(second)==11 and not ids(first)&ids(second)
    assert any(x['kind']=='job' for x in second)
    reset_role(c)


def test_schedule_save_rejects_stale_account_state(synced):
    c=synced
    account=db.one(c,'select * from social_accounts limit 1')
    expected={'enabled':account['enabled'],'weekly_targets':account['weekly_targets']}
    db.run(c,'update social_accounts set enabled=not enabled where id=%s',(account['id'],))
    owner(c)
    with pytest.raises(psycopg.Error,match='changed elsewhere'):
        db.one(c,'select save_posting_schedule(%s,%s,%s,false)',(account['id'],db.j({}),db.j(expected)))
    reset_role(c)


def test_server_rescheduling_rejects_clashes_and_past_times(synced):
    from datetime import date, timedelta
    from studio import produce
    c=synced
    acc=db.one(c,'select id from social_accounts limit 1')['id']
    p=produce.ensure_project(c,'ai','long','Schedule test',date.today())
    ids=[]
    for i in range(2):
        variant=db.one(c,"insert into content_variants(project_id,social_account_id,kind) values(%s,%s,'text_post') returning id",(p['id'],acc))['id']
        ids.append(db.one(c,"insert into scheduled_posts(variant_id,social_account_id,scheduled_at,status,idempotency_key) values(%s,%s,now()+make_interval(days=>%s),'pending_approval',%s) returning id",(variant,acc,i+1,f'schedule-test-{i}'))['id'])
    future=datetime.now(timezone.utc)+timedelta(days=3)
    owner(c)
    c.execute('select reschedule_post(%s,%s)',(ids[0],future))
    with pytest.raises(psycopg.Error,match='within 30 minutes'):
        c.execute('select reschedule_post(%s,%s)',(ids[1],future+timedelta(minutes=10)))
    with pytest.raises(psycopg.Error,match='future time'):
        c.execute('select reschedule_post(%s,now()-interval \'1 minute\')',(ids[1],))
    reset_role(c)
