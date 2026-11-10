"""Actual database confirmation and delayed TikTok processing; platform requests stay offline."""
from datetime import datetime, timezone

import psycopg
import pytest

from studio import db
from studio.publish import adapters, runner
from .test_tiktok_direct import _Client


@pytest.fixture
def tiktok_post(synced):
    conn = synced
    acc = db.one(conn, "select id from social_accounts where platform='tiktok' limit 1")
    project = db.one(conn, """insert into content_projects(channel_slug,format,title,status,recipe)
        values ('ai','short','TikTok test','approved',%s) returning *""",
        (db.j({'preview_key': 'preview.mp4', 'render': {'scenes': []}}),))
    variant = db.one(conn, """insert into content_variants(project_id,social_account_id,kind,body,hashtags,status)
        values (%s,%s,'short_video','Saved caption',array['ai'],'approved') returning *""", (project['id'], acc['id']))
    post = db.one(conn, """insert into scheduled_posts(variant_id,social_account_id,scheduled_at,status,idempotency_key)
        values (%s,%s,now(),'scheduled','tiktok:test') returning *""", (variant['id'], acc['id']))
    snapshot = db.one(conn, 'select tiktok_content_snapshot(%s) s', (post['id'],))['s']
    return conn, post, project, snapshot


def confirm(conn, post, snapshot):
    return db.one(conn, 'select confirm_tiktok_post(%s,%s,%s) s', (post['id'], db.j({
        'privacy_level': 'PUBLIC_TO_EVERYONE', 'consent': True, 'allow_comment': False,
    }), db.j(snapshot)))['s']


def test_confirmation_records_exact_saved_content(tiktok_post):
    conn, post, _, snapshot = tiktok_post
    saved = confirm(conn, post, snapshot)
    assert saved['content_snapshot'] == snapshot and saved['confirmed_at']
    assert snapshot['body'] == 'Saved caption' and snapshot['preview_key'] == 'preview.mp4'
    assert not db.one(conn, "select has_function_privilege('authenticated','public.confirm_tiktok_post(uuid,jsonb,jsonb)','EXECUTE') ok")['ok']
    assert not db.one(conn, "select has_function_privilege('anon','public.tiktok_content_snapshot(uuid)','EXECUTE') ok")['ok']


@pytest.mark.parametrize('change', ['caption', 'recipe', 'account'])
def test_confirmation_refuses_stale_content(tiktok_post, change):
    conn, post, project, snapshot = tiktok_post
    if change == 'caption':
        db.run(conn, "update content_variants set body='Changed caption' where id=%s", (post['variant_id'],))
    elif change == 'recipe':
        db.run(conn, 'update content_projects set recipe=recipe || %s where id=%s', (db.j({'render': {'scenes': [{'text': 'new'}]}}), project['id']))
    else:
        db.run(conn, "update social_accounts set external_id='another-creator' where id=%s", (post['social_account_id'],))
    with pytest.raises(psycopg.errors.RaiseException, match='changed'):
        confirm(conn, post, snapshot)
    assert db.one(conn, 'select tiktok_post from scheduled_posts where id=%s', (post['id'],))['tiktok_post'] is None


def ready(tiktok_post, monkeypatch, tmp_path):
    conn, post, project, snapshot = tiktok_post
    confirm(conn, post, snapshot)
    db.run(conn, "update oauth_connections set status='connected',scopes=array['video.publish'] where social_account_id=%s", (post['social_account_id'],))
    monkeypatch.setattr(runner, 'safety_problems', lambda *a: [])
    monkeypatch.setattr(runner.oauth, 'access_token', lambda *a: ('mock-token', {}))
    monkeypatch.setattr(adapters, '_connected', lambda *a: True)
    monkeypatch.setattr(adapters, '_seconds', lambda *a: 30)
    video = tmp_path / 'video.mp4'; video.write_bytes(b'video')
    monkeypatch.setattr(runner, 'final_media', lambda *a: (video, None))
    post = runner.claim_due(conn)[0]
    return conn, post, project


def test_processing_is_reconciled_once_without_another_upload(tiktok_post, monkeypatch, tmp_path):
    conn, post, _ = ready(tiktok_post, monkeypatch, tmp_path)
    client = _Client(status='PROCESSING_UPLOAD'); adapter = adapters.TikTok(client)
    adapter.polls = 1; adapter.poll_seconds = 0
    assert runner.publish_post(conn, None, post, {'tiktok': adapter}) == 'processing'
    assert db.one(conn, 'select status from scheduled_posts where id=%s', (post['id'],))['status'] == 'processing'
    assert db.one(conn, 'select count(*) n from published_posts')['n'] == 0
    assert db.one(conn, 'select outcome from publish_attempts')['outcome'] is None
    with pytest.raises(psycopg.errors.RaiseException, match='uploading'):
        db.run(conn, "update content_variants set body='Changed' where id=%s", (post['variant_id'],))
    with pytest.raises(psycopg.errors.RaiseException, match='cannot be changed'):
        confirm(conn, post, {})
    client.status = 'PUBLISH_COMPLETE'
    assert runner.check_tiktok_processing(conn, {'tiktok': adapter}, datetime.now(timezone.utc)) == {'published': 1}
    assert runner.check_tiktok_processing(conn, {'tiktok': adapter}, datetime.now(timezone.utc)) == {}
    assert db.one(conn, 'select count(*) n from published_posts')['n'] == 1
    assert sum(path == 'post/publish/video/init/' for path, _ in client.calls) == 1


def test_changed_content_after_confirmation_is_stopped_before_upload(tiktok_post, monkeypatch, tmp_path):
    conn, post, _ = ready(tiktok_post, monkeypatch, tmp_path)
    db.run(conn, "update scheduled_posts set status='scheduled' where id=%s", (post['id'],))
    db.run(conn, "update content_variants set body='A different caption' where id=%s", (post['variant_id'],))
    client = _Client(); adapter = adapters.TikTok(client)
    assert runner.publish_post(conn, None, post, {'tiktok': adapter}) == 'failed'
    assert not client.calls
    assert db.one(conn, 'select count(*) n from published_posts')['n'] == 0


def test_failed_processing_does_not_record_success_or_resend(tiktok_post, monkeypatch, tmp_path):
    conn, post, _ = ready(tiktok_post, monkeypatch, tmp_path)
    client = _Client(status='PROCESSING_UPLOAD'); adapter = adapters.TikTok(client)
    adapter.polls = 1; adapter.poll_seconds = 0
    assert runner.publish_post(conn, None, post, {'tiktok': adapter}) == 'processing'
    client.status = 'FAILED'
    assert runner.check_tiktok_processing(conn, {'tiktok': adapter}, datetime.now(timezone.utc)) == {'failed': 1}
    stored = db.one(conn, 'select status,tiktok_upload from scheduled_posts where id=%s', (post['id'],))
    assert stored['status'] == 'failed' and stored['tiktok_upload'] is None
    assert db.one(conn, 'select count(*) n from published_posts')['n'] == 0
    assert sum(path == 'post/publish/video/init/' for path, _ in client.calls) == 1


def test_dropped_upload_remembers_id_and_only_checks_status(tiktok_post, monkeypatch, tmp_path):
    import httpx
    conn, post, _ = ready(tiktok_post, monkeypatch, tmp_path)
    client = _Client()
    def dropped(*a, **k):
        raise httpx.TransportError('upload connection dropped')
    client.put = dropped
    adapter = adapters.TikTok(client)
    assert runner.publish_post(conn, None, post, {'tiktok': adapter}) == 'processing'
    assert db.one(conn, 'select tiktok_upload from scheduled_posts where id=%s', (post['id'],))['tiktok_upload']['publish_id'] == 'p1'
    assert runner.check_tiktok_processing(conn, {'tiktok': adapter}, datetime.now(timezone.utc)) == {'published': 1}
    assert sum(path == 'post/publish/video/init/' for path, _ in client.calls) == 1
