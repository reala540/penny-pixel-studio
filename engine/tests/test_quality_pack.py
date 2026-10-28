"""Quality pack: the publisher only trusts what it can check (the approval of the current version, the final video
made from the current recipe, Facebook's explicit yes), Facebook errors say what to do, clock changes are handled on
purpose, Facebook Reels and text posts can have their own times, approving with problems needs a reason, capacity uses
the real video length, photos are chosen by how well they match, and Settings shows what each account can really do.
Everything outside the database is mocked; nothing is posted."""

from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import httpx
import psycopg
import pytest

from studio import capacity, db, produce, schedule
from studio.errors import AmbiguousPublish, AuthError, QuotaError
from studio.media import stock
from studio.publish import adapters, capabilities, runner

from .test_audit_fixes import OWNER, _claim_owner, _package
from .test_database import as_user, reset_role
from .test_end_to_end import Platform, _adapters, _approve_all, _connect_all, produced, silent_tts  # noqa: F401
from .test_facebook_kinds import ALL_WEEK, _fb, _kinds, _plan
from .test_strict_publishing import LATER, _one_post, _ready


# ------------------------------------------------------------------ 1, 5: approval of the current version, final video

def test_an_approval_of_an_earlier_version_does_not_count(produced):
    conn, storage = produced
    _ready(conn)
    post = _one_post(conn, "facebook")
    pid = db.one(conn, "select project_id from content_variants where id=%s", (post["variant_id"],))["project_id"]
    # the package's approval record is for another version than the current one (e.g. made before an edit)
    db.run(conn, "delete from approvals where target_type='project' and target_id=%s", (pid,))
    db.run(conn, "insert into approvals (target_type, target_id, decision, script_version_id) values ('project',%s,'approved',null)",
           (pid,))
    platform = Platform()
    assert runner.publish_post(conn, storage, post, _adapters(platform), now=LATER) == "blocked"
    assert platform.requests == []
    assert "current script version" in db.one(conn, "select last_error from scheduled_posts where id=%s", (post["id"],))["last_error"]


def test_the_final_video_is_named_by_what_is_in_it(tmp_path):
    photo = tmp_path / "a.jpg"
    photo.write_bytes(b"photo")
    recipe = {"scenes": [{"narration": "Hello", "visual": {"type": "title_card"}}]}
    a = runner.recipe_fingerprint(recipe, {}, {}, {})
    assert a == runner.recipe_fingerprint(recipe, {}, {}, {})                      # same content, same file
    edited = {"scenes": [{"narration": "Hello again", "visual": {"type": "title_card"}}]}
    assert runner.recipe_fingerprint(edited, {}, {}, {}) != a                       # an edit never reuses the old file
    assert runner.recipe_fingerprint(recipe, {0: photo}, {}, {}) != a                # nor a different photo


def test_a_reused_workspace_never_publishes_the_old_video(produced, monkeypatch):
    conn, storage = produced
    _ready(conn)
    post = _one_post(conn, "youtube")
    ctx = runner._context(conn, post)
    made = []
    real = runner.rendering.render

    def counting(recipe, out, *a, **k):
        made.append(Path(out).name)
        return real(recipe, out, *a, **k)

    monkeypatch.setattr(runner.rendering, "render", counting)
    first, _ = runner.final_media(conn, storage, ctx)
    again, _ = runner.final_media(conn, storage, ctx)
    assert first == again and len(made) == 1                                       # unchanged: the file is reused
    ctx["recipe"]["render"]["scenes"][0]["narration"] += " Edited."
    edited, _ = runner.final_media(conn, storage, ctx)
    assert edited != first and len(made) == 2                                      # changed: made again


# ------------------------------------------------------------------ 2, 3: Facebook acknowledgements and errors

def _facebook(handler):
    return adapters.Facebook(httpx.Client(transport=httpx.MockTransport(handler)))


def _reel_flow(finish: dict):
    def handler(req):
        u = str(req.url)
        if "rupload" in u:
            return httpx.Response(200, json={"success": True})
        if "video_reels" in u and b"start" in req.content:
            return httpx.Response(200, json={"video_id": "v1"})
        return httpx.Response(200, json=finish)
    return handler


def test_a_reel_without_facebooks_yes_is_not_called_posted(tmp_path):
    video = tmp_path / "r.mp4"
    video.write_bytes(b"x")
    reel = {"kind": "reel", "body": "Hi"}
    with pytest.raises(AmbiguousPublish, match="didn't confirm"):
        _facebook(_reel_flow({})).publish(None, {}, reel, video, None, "t", "page")             # no answer at all
    with pytest.raises(AmbiguousPublish):
        _facebook(_reel_flow({"success": False})).publish(None, {}, reel, video, None, "t", "page")
    assert _facebook(_reel_flow({"success": True})).publish(None, {}, reel, video, None, "t", "page").platform_post_id == "v1"


def test_a_text_post_without_an_id_is_not_called_posted():
    fb = _facebook(lambda req: httpx.Response(200, json={}))
    with pytest.raises(AmbiguousPublish, match="no post id"):
        fb.publish(None, {}, {"kind": "text_post", "body": "Hi"}, None, None, "t", "page")


@pytest.mark.parametrize("code, error, words", [
    (190, AuthError, "login expired"), (102, AuthError, "login expired"),
    (200, AuthError, "permission is missing"), (10, AuthError, "permission is missing"),
    (4, QuotaError, "rate limit"), (32, QuotaError, "rate limit"),
])
def test_facebook_errors_say_what_to_do(code, error, words):
    fb = _facebook(lambda req: httpx.Response(400, json={"error": {"message": "Error validating access token", "type": "OAuthException", "code": code}}))
    with pytest.raises(error, match=words):
        fb.publish(None, {}, {"kind": "text_post", "body": "Hi"}, None, None, "t", "page")


def test_an_expired_facebook_login_asks_for_reconnect_not_a_retry(produced):
    conn, storage = produced
    _ready(conn)
    post = _one_post(conn, "facebook")

    def expired(req):
        return httpx.Response(400, json={"error": {"message": "Session has expired", "type": "OAuthException", "code": 190}})

    out = runner.publish_post(conn, storage, post, {**_adapters(Platform()), "facebook": _facebook(expired)}, now=LATER)
    assert out == "auth_failed"
    c = db.one(conn, "select status, last_error from oauth_connections where social_account_id=%s", (post["social_account_id"],))
    assert c["status"] != "connected" and "Reconnect Facebook" in c["last_error"]


# ------------------------------------------------------------------ 7: clock changes

def test_a_skipped_time_moves_forward_and_says_so():
    notes: list[str] = []
    out = schedule.slots(["sun"], ["02:30"], date(2027, 3, 8), "America/New_York", notes=notes)
    assert out == [datetime(2027, 3, 14, 7, 30, tzinfo=timezone.utc)]               # 03:30 New York (EDT)
    assert "doesn't exist" in notes[0] and "03:30" in notes[0]


def test_a_time_that_happens_twice_uses_the_first():
    notes: list[str] = []
    out = schedule.slots(["sun"], ["01:30"], date(2026, 10, 26), "America/New_York", notes=notes)
    assert out == [datetime(2026, 11, 1, 5, 30, tzinfo=timezone.utc)]               # the first 01:30 (still EDT)
    assert "happens twice" in notes[0]


def test_an_ordinary_day_has_no_note():
    notes: list[str] = []
    schedule.slots(["mon"], ["18:00"], date(2026, 11, 2), "Africa/Nairobi", notes=notes)
    assert notes == []


# ------------------------------------------------------------------ 11: Facebook Reels and text posts on their own times

def test_reels_and_text_posts_can_have_their_own_times(produced):
    conn, _ = produced
    db.run(conn, "delete from scheduled_posts where social_account_id=%s", (_fb(conn)["id"],))
    db.run(conn, "delete from content_variants where social_account_id=%s", (_fb(conn)["id"],))
    _plan(conn, reel=1, text_post=1, posting_days=ALL_WEEK, posting_times=["12:00"],
          reel_days=ALL_WEEK, reel_times=["19:00"], text_days=ALL_WEEK, text_times=["08:00"])
    tz = db.get_setting(conn, "timezone", "Africa/Nairobi")
    hours = {r["kind"]: schedule.to_local(r["scheduled_at"], tz).strftime("%H:%M") for r in _kinds(conn)}
    assert hours.get("reel") == "19:00" and hours.get("text_post") == "08:00"


def test_without_their_own_times_they_use_the_pages():
    t = {"posting_days": ["mon"], "posting_times": ["12:00"], "reel_days": ["tue"], "reel_times": []}
    assert produce.schedule_for(t, "reel") == (["mon"], ["12:00"])      # half-set: falls back, nothing half-applied
    assert produce.schedule_for(t, "text") == (["mon"], ["12:00"])
    t["reel_times"] = ["19:00"]
    assert produce.schedule_for(t, "reel") == (["tue"], ["19:00"])


def test_the_schedule_editor_saves_facebook_times_and_keeps_stories_after_their_reel(produced):
    conn, _ = produced
    _claim_owner(conn)
    fb = _fb(conn)
    _plan(conn, reel=1, story=1, text_post=1, posting_days=ALL_WEEK)
    as_user(conn, OWNER)
    out = db.one(conn, "select set_posting_schedule(%s, %s, true) r", (fb["id"], db.j({"reel_days": ["sat"], "reel_times": ["20:00"]})))["r"]
    reset_role(conn)
    assert out["weekly_targets"]["reel_days"] == ["sat"]
    rows = _kinds(conn)
    reel = next(r for r in rows if r["kind"] == "reel")
    story = next((r for r in rows if r["kind"] == "story" and r["project_id"] == reel["project_id"]), None)
    tz = db.get_setting(conn, "timezone", "Africa/Nairobi")
    assert schedule.to_local(reel["scheduled_at"], tz).strftime("%a %H:%M") == "Sat 20:00"
    if story:
        assert story["scheduled_at"] == reel["scheduled_at"] + timedelta(hours=3)
    yt = db.one(conn, "select id from social_accounts where platform='youtube' limit 1")["id"]
    as_user(conn, OWNER)
    with pytest.raises(psycopg.Error, match="only for Facebook"):
        conn.execute("select set_posting_schedule(%s, %s)", (yt, db.j({"reel_days": ["sat"]})))
    reset_role(conn)


# ------------------------------------------------------------------ 6: approving with problems needs a reason

def test_approving_with_unsupported_facts_needs_a_written_reason(synced):
    c = synced
    _claim_owner(c)
    p, v1, _ = _package(c)
    db.run(c, """insert into research_claims (project_id, script_version_id, claim_key, claim_text, status)
                 values (%s,%s,'k','Rates fell 9%% last week','unsupported')""", (p, v1))
    as_user(c, OWNER)
    with pytest.raises(psycopg.Error, match="write why you are approving anyway"):
        c.execute("select approve_project(%s, null, %s)", (p, v1))
    with pytest.raises(psycopg.Error, match="write why"):
        c.execute("select approve_project(%s, 'ok', %s)", (p, v1))                  # too short to be a reason
    assert db.one(c, "select approve_project(%s, 'I checked the rate on the bank site myself.', %s) n", (p, v1))["n"] == 1
    reset_role(c)
    a = db.one(c, "select notes from approvals where target_type='project' and target_id=%s", (p,))
    assert a["notes"].startswith("I checked")
    log = db.one(c, "select details from audit_logs where action='approved_with_problems' and target_id=%s", (str(p),))
    assert log["details"]["unsupported_facts"] == 1 and log["details"]["reason"].startswith("I checked")


def test_a_clean_package_needs_no_reason(synced):
    c = synced
    _claim_owner(c)
    p, v1, _ = _package(c)
    as_user(c, OWNER)
    assert db.one(c, "select approve_project(%s, null, %s) n", (p, v1))["n"] == 1
    reset_role(c)
    assert db.one(c, "select count(*) n from audit_logs where action='approved_with_problems'")["n"] == 0


# ------------------------------------------------------------------ 8: capacity

def test_capacity_uses_the_real_video_length(synced):
    c = synced
    assert capacity.long_seconds(None) == 11 * 60                                   # the configured target, not 7 minutes
    for _ in range(3):
        capacity.record_render(c, None, "final", 900, 600, 1)                        # three measured 10-minute videos
    assert capacity.long_seconds(c) == 600
    plan = capacity.plan_batch(c)
    assert plan["assumptions"]["long_video_minutes"] == 10.0
    assert plan["assumptions"]["animated_scenes_per_package"] >= 1 and plan["assumptions"]["retry_allowance"] > 1


# ------------------------------------------------------------------ 10: photos chosen by how well they match

def test_the_best_matching_photo_wins_not_the_first(tmp_path, monkeypatch):
    monkeypatch.setenv("PEXELS_API_KEY", "k")
    monkeypatch.delenv("PIXABAY_API_KEY", raising=False)

    def handler(req):
        if "api.pexels.com" in str(req.url):
            return httpx.Response(200, json={"photos": [
                {"url": "https://www.pexels.com/photo/beach-sunset-1/", "alt": "Beach at sunset", "photographer": "A",
                 "width": 6000, "height": 4000, "src": {"large2x": "https://img/beach.jpg"}},
                {"url": "https://www.pexels.com/photo/coins-in-a-jar-2/", "alt": "Coins in a glass jar", "photographer": "B",
                 "width": 3000, "height": 2000, "src": {"large2x": "https://img/coins.jpg"}}]})
        return httpx.Response(200, content=b"jpeg")

    hit = stock.find_photo("coins jar savings", tmp_path, client=httpx.Client(transport=httpx.MockTransport(handler)))
    assert hit is not None and hit.creator == "B"


def test_why_there_was_no_photo_is_recorded(tmp_path, monkeypatch):
    monkeypatch.delenv("PEXELS_API_KEY", raising=False)
    monkeypatch.delenv("PIXABAY_API_KEY", raising=False)
    problems: list[str] = []
    client = httpx.Client(transport=httpx.MockTransport(lambda req: httpx.Response(503)))
    assert stock.find_photo("coins", tmp_path, client=client, problems=problems) is None
    assert problems == ["pixabay: no key saved", "pexels: no key saved", "openverse: refused (503)"]


def test_a_backup_card_carries_its_reason(synced, tmp_path, monkeypatch):
    monkeypatch.setattr(stock, "find_video", lambda *a, **k: None)
    monkeypatch.setattr(stock, "find_photo", lambda q, d, o, problems=None: problems.append("pexels: nothing suitable") or None)
    recipe = {"format": "long", "title": "T", "scenes": [{"narration": "n", "visual": {"type": "stock", "stock_query": "coins jar"}}]}
    produce.attach_media(synced, None, None, recipe, tmp_path)
    v = recipe["scenes"][0]["visual"]
    assert v["type"] == "title_card" and "coins jar" in v["fallback_reason"] and "pexels: nothing suitable" in v["fallback_reason"]


# ------------------------------------------------------------------ 12: what each account can really do

def test_settings_shows_what_each_account_can_really_do(produced):
    conn, _ = produced
    snap = capabilities.snapshot(conn, _adapters(Platform()))
    assert all(not a["can_publish"] and a["next_step"] == "Press Connect and sign in." for a in snap["accounts"].values())
    _connect_all(conn)
    fb = _fb(conn)
    db.run(conn, "update oauth_connections set scopes='{pages_show_list}' where social_account_id=%s", (fb["id"],))
    snap = capabilities.snapshot(conn, _adapters(Platform()))
    mine = snap["accounts"][str(fb["id"])]
    assert mine["login_saved"] and not mine["can_publish"]
    assert mine["permissions_missing"] == ["pages_read_engagement", "pages_manage_posts"]
    assert "Reconnect" in mine["next_step"]
    assert db.get_setting(conn, "account_capabilities")["accounts"][str(fb["id"])]["permissions_missing"]
