"""Facebook Stories and long videos on the Page: planned from the owner's weekly numbers, a Story three hours after
its Reel, published with Facebook's own upload flows (mocked here), and never mistaken for a duplicate of the Reel."""

from datetime import timedelta
from pathlib import Path

import httpx
import psycopg
import pytest

from studio import db, produce
from studio.publish import adapters, runner

from .test_database import reset_role
from .test_end_to_end import Platform, _adapters, _approve_all, _connect_all, produced, silent_tts  # noqa: F401
from .test_setup_schedule import account, owner


def _fb(conn):
    return db.one(conn, "select * from social_accounts where platform='facebook'")


ALL_WEEK = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]  # room for a long video next to the Reels and posts


def _plan(conn, **targets):
    fb = _fb(conn)
    db.run(conn, "update social_accounts set weekly_targets = weekly_targets || %s where id=%s", (db.j(targets), fb["id"]))
    week = db.one(conn, "select max(batch_week) w from content_projects")["w"]
    return produce.plan_distribution(conn, week)


def _kinds(conn):
    return db.all_(conn, """select v.kind, v.project_id, v.title, v.body, sp.scheduled_at from content_variants v
                            join scheduled_posts sp on sp.variant_id=v.id where v.social_account_id=%s order by sp.scheduled_at""",
                   (_fb(conn)["id"],))


def test_stories_follow_their_reels_and_long_videos_take_a_slot(produced):
    conn, _ = produced
    before = {r["kind"] for r in _kinds(conn)}
    assert "story" not in before and "long_video" not in before  # nothing new until the owner asks for it
    _plan(conn, story=2, long_video=1, posting_days=ALL_WEEK)
    rows = _kinds(conn)
    reels = {r["project_id"]: r["scheduled_at"] for r in rows if r["kind"] == "reel"}
    stories = [r for r in rows if r["kind"] == "story"]
    assert 1 <= len(stories) <= 2
    for s in stories:
        assert s["scheduled_at"] == reels[s["project_id"]] + timedelta(hours=3)
    longs = [r for r in rows if r["kind"] == "long_video"]
    assert len(longs) == 1 and longs[0]["title"] and longs[0]["body"]  # the YouTube title and description
    # planning again adds nothing twice
    n = len(rows)
    _plan(conn, story=2, long_video=1, posting_days=ALL_WEEK)
    assert len(_kinds(conn)) == n


def test_story_and_long_video_publish_through_facebook(produced):
    conn, storage = produced
    _plan(conn, story=1, long_video=1, posting_days=ALL_WEEK)
    _connect_all(conn)
    _approve_all(conn)
    db.run(conn, "update content_projects set fresh_until = now() + interval '60 days'")
    platform = Platform()
    later = db.one(conn, "select max(scheduled_at) t from scheduled_posts")["t"] + timedelta(hours=1)
    runner.run_due(conn, storage, _adapters(platform), now=later)
    done = {r["kind"]: r for r in db.all_(conn, """select v.kind, sp.status, sp.last_error from scheduled_posts sp
                                                   join content_variants v on v.id=sp.variant_id
                                                   where v.social_account_id=%s""", (_fb(conn)["id"],))}
    assert done["story"]["status"] == "published", done["story"]["last_error"]   # not blocked as a repeat of its Reel
    assert done["reel"]["status"] == "published"
    sent = [u for _, u in platform.requests]
    assert any("video_stories" in u for u in sent)
    assert done["long_video"]["status"] == "published", done["long_video"]["last_error"]
    assert any("graph-video.facebook.com" in u for u in sent)


def test_fingerprint_marks_stories_only(tmp_path):
    f = tmp_path / "v.mp4"
    f.write_bytes(b"same video")
    reel, story = runner.fingerprint({"kind": "reel"}, f), runner.fingerprint({"kind": "story"}, f)
    assert reel != story and story == runner.fingerprint({"kind": "story"}, f)
    assert runner.fingerprint({"kind": "short_video"}, f) == reel   # existing fingerprints unchanged


class _Recorder:
    def __init__(self, inner):
        self.inner, self.bodies = inner, []

    def __call__(self, req):
        self.bodies.append((str(req.url), req.content))
        return self.inner(req)


def test_long_video_is_sent_in_pieces_and_a_story_has_no_caption(tmp_path):
    video = tmp_path / "long.mp4"
    video.write_bytes(b"x" * ((1 << 20) * 2 + 123))   # three pieces
    rec = _Recorder(Platform())
    fb = adapters.Facebook(httpx.Client(transport=httpx.MockTransport(rec)))
    res = fb.publish(None, {}, {"kind": "long_video", "title": "AI ROI", "body": "Description. Not financial advice."},
                     video, None, "tok", "123")
    assert res.platform_post_id == "fbv1" and "/videos/fbv1" in res.url
    transfers = [b for u, b in rec.bodies if b"transfer" in b]
    assert len(transfers) == 3 and sum(len(b) for b in transfers) > video.stat().st_size
    assert any(b"title=AI+ROI" in b for u, b in rec.bodies if b"upload_phase=finish" in b)
    rec.bodies.clear()
    short = tmp_path / "s.mp4"
    short.write_bytes(b"short")
    res = fb.publish(None, {}, {"kind": "story", "body": "caption", "hashtags": ["ai"]}, short, None, "tok", "123")
    assert res.platform_post_id == "page_story1"
    assert not any(b"caption" in b or b"description" in b for _, b in rec.bodies)


def test_a_story_needs_a_video():
    fb = adapters.Facebook(httpx.Client(transport=httpx.MockTransport(Platform())))
    with pytest.raises(adapters.PermanentError):
        fb.publish(None, {}, {"kind": "story"}, None, None, "tok", "123")


def test_schedule_accepts_facebook_stories_and_long_videos_only_on_facebook(synced):
    c = synced
    owner(c)
    fb, x = account(c, "Facebook Page"), account(c, "X")
    out = db.one(c, "select public.set_posting_schedule(%s, %s) r", (fb["id"], db.j({"targets": {"story": 3, "long_video": 1}})))["r"]
    assert out["weekly_targets"]["story"] == 3 and out["weekly_targets"]["long_video"] == 1
    with pytest.raises(psycopg.errors.RaiseException):
        db.one(c, "select public.set_posting_schedule(%s, %s) r", (x["id"], db.j({"targets": {"story": 1}})))
    reset_role(c)
    check = db.one(c, """select pg_get_constraintdef(oid) d from pg_constraint
                         where conname='content_variants_kind_check'""")["d"]
    assert "'story'" in check
