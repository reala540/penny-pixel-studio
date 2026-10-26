"""The daily heads-up: tomorrow's posts and whether each will go out by itself. It only reads: nothing is sent to a
platform, no post changes, and it's sent once a day."""

from datetime import timedelta

from studio import db
from studio.publish import heads_up

from .test_end_to_end import Platform, _adapters, _approve_all, _connect_all, produced, silent_tts  # noqa: F401


def _ready(conn):
    _connect_all(conn)
    _approve_all(conn)
    db.run(conn, "update content_projects set fresh_until = now() + interval '60 days'")
    db.run(conn, "update scheduled_posts set status='scheduled'")
    db.run(conn, "update channel_profiles set launch_date = null")


def _first(conn, platform: str) -> dict:
    return db.one(conn, """select sp.* from scheduled_posts sp join social_accounts a on a.id = sp.social_account_id
                           where a.platform=%s and sp.status='scheduled' order by sp.scheduled_at limit 1""", (platform,))


def _check(conn, post, platform=None):
    return heads_up.check_post(conn, post, _adapters(platform or Platform()), post["scheduled_at"] - timedelta(hours=2))


def test_ready_posts_and_youtube_needs_one_tap(produced):
    conn, _ = produced
    _ready(conn)
    assert _check(conn, _first(conn, "x"))[0] == heads_up.READY
    assert _check(conn, _first(conn, "facebook")) == (heads_up.READY, "will post by itself")
    state, what = _check(conn, _first(conn, "youtube"))
    assert state == heads_up.ONE_TAP and "Public in YouTube Studio" in what


def test_problems_are_found_the_day_before(produced):
    conn, _ = produced
    _ready(conn)
    fb = _first(conn, "facebook")
    db.run(conn, "update oauth_connections set status='disconnected' where social_account_id=%s", (fb["social_account_id"],))
    state, what = _check(conn, fb)
    assert state == heads_up.NEEDS_YOU and "not connected" in what and "copy-and-paste" in what

    x = _first(conn, "x")
    db.run(conn, "update content_projects set fresh_until=%s where id=(select project_id from content_variants where id=%s)",
           (x["scheduled_at"] - timedelta(minutes=1), x["variant_id"]))
    assert "out of date" in _check(conn, x)[1]  # judged at posting time, not now

    db.run(conn, "insert into settings (key, value) values ('paused', 'true') on conflict (key) do update set value='true'")
    assert "paused" in _check(conn, _first(conn, "youtube"))[1]


def test_x_link_and_launch_date(produced):
    conn, _ = produced
    _ready(conn)
    x = _first(conn, "x")
    db.run(conn, "update content_variants set body='Read this https://example.com' where id=%s", (x["variant_id"],))
    assert "link" in _check(conn, x)[1]
    db.run(conn, "update channel_profiles set launch_date = current_date + 400")
    assert "launch date" in _check(conn, _first(conn, "facebook"))[1]


def test_send_reads_only_and_sends_once_a_day(produced):
    conn, _ = produced
    _ready(conn)
    first = db.one(conn, "select min(scheduled_at) t from scheduled_posts where status='scheduled'")["t"]
    before = db.all_(conn, "select id, status, attempts, last_error from scheduled_posts order by id")
    platform = Platform()
    now = first - timedelta(hours=1)
    msg = heads_up.send(conn, now, adapters=_adapters(platform))
    assert msg and msg["title"].startswith("Next 24 hours:")
    assert "time." in msg["body"] and "✅" in msg["body"]
    assert platform.requests == []                                                 # nothing sent to any platform
    assert db.all_(conn, "select id, status, attempts, last_error from scheduled_posts order by id") == before
    assert db.one(conn, "select count(*) n from publish_attempts")["n"] == 0
    heads_up.send(conn, now + timedelta(minutes=30), adapters=_adapters(platform))  # a rerun the same day
    rows = db.all_(conn, "select kind, link from notifications where dedupe_key like 'heads_up:%%'")
    assert len(rows) == 1 and rows[0]["link"].endswith("/calendar")
    assert rows[0]["kind"] == ("posts_need_you" if msg["needs_you"] else "posts_ready")


def test_nothing_due_sends_nothing(produced):
    conn, _ = produced
    _ready(conn)
    last = db.one(conn, "select max(scheduled_at) t from scheduled_posts")["t"]
    assert heads_up.send(conn, last + timedelta(days=2), adapters=_adapters(Platform())) is None
    assert db.one(conn, "select count(*) n from notifications where dedupe_key like 'heads_up:%%'")["n"] == 0
