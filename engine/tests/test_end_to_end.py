"""End-to-end journeys from the blueprint (external APIs mocked; DB, FFmpeg rendering and job system real).

1. Research -> Script -> Video -> Review
2. Approval -> Scheduling -> Publishing
3. Provider outage -> free fallback
4. Failed render -> resume
5. Expired finance data -> publication blocked
6. Budget exhaustion -> X requests disabled
7. Unverified platform API -> manual / draft fallback
8. Duplicate publish attempt -> safe prevention
"""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import psycopg
import pytest

from studio import config, db, oauth, produce
from studio.media import render as rendering
from studio.publish import adapters, runner
from studio.research import engine as research
from studio.research.sources import Fetcher
from studio.storage import LocalStorage

from .fakes import ScriptedRouter, fake_sources

RSS = """<?xml version="1.0"?><rss><channel>
<item><title>Inflation cools to 2.9 percent</title><link>https://news.example/a</link>
<pubDate>Wed, 21 Oct 2026 10:00:00 GMT</pubDate><description>Prices rose 2.9 percent in September 2026.</description>
<source url="https://news.example">Example News</source></item>
<item><title>New open model beats paid rivals on coding</title><link>https://news.example/b</link>
<pubDate>Thu, 22 Oct 2026 10:00:00 GMT</pubDate><description>The model scored 71 percent on a coding test.</description></item>
</channel></rss>"""


@pytest.fixture()
def silent_tts(monkeypatch):
    monkeypatch.setenv("STUDIO_TTS", "silent")
    monkeypatch.setenv("STUDIO_RENDER_SCALE", "0.25")
    monkeypatch.setenv("STUDIO_FPS", "6")
    monkeypatch.setattr("studio.media.render.FPS", 6)
    monkeypatch.setattr("studio.script.quality.MIN_LONG_SECONDS", 20)
    monkeypatch.setattr("tests.fakes.FILLER_SENTENCE_GROUPS", 1)


def test_research_collect_parses_and_dedupes(synced, monkeypatch):
    def handler(req):
        if "hn.algolia.com" in str(req.url):
            return httpx.Response(200, json={"hits": [{"objectID": "1", "title": "Show HN: tiny LLM", "url": "https://x.test",
                                                       "points": 300, "num_comments": 50, "created_at": "2026-10-22T10:00:00Z"}]})
        if "trends.google.com" in str(req.url):
            return httpx.Response(200, text="<rss><channel><item><title>ai agents</title></item></channel></rss>")
        return httpx.Response(200, text=RSS)

    f = Fetcher(httpx.Client(transport=httpx.MockTransport(handler)))
    r1 = research.collect(synced, f)
    r2 = research.collect(synced, f)
    assert r1["google_news_rss"]["ok"] and r1["google_news_rss"]["new"] >= 2
    assert all(v.get("new", 0) == 0 for v in r2.values() if v.get("ok"))  # dedupe by content hash
    assert r1.get("fred", {}).get("items", 0) == 0  # no key -> skipped, not faked
    topics = {r["topic"] for r in db.all_(synced, "select topic from research_sources")}
    assert {"ai", "money"} <= topics


def _produce_week(conn, monkeypatch, failing=None):
    router = ScriptedRouter(monkeypatch, failing=failing)
    week = research.week_start()
    fake_sources(conn, "money")
    fake_sources(conn, "ai")
    for ch in ("ai", "money"):
        research.run_ideas(conn, router, ch, 1, week)
    monkeypatch.setattr("studio.capacity.plan_batch", lambda c, today=None: {"long_per_channel": {"ai": 1, "money": 1}})
    storage = LocalStorage(Path(config.runtime().work_dir) / "storage")
    out = produce.produce_batch(conn, router, storage, week)
    return router, storage, week, out


def test_journey_research_script_video_review(synced, monkeypatch, silent_tts):
    router, storage, week, out = _produce_week(synced, monkeypatch)
    statuses = {p["status"] for p in out["projects"]}
    assert statuses == {"ready_for_review"}, out
    longs = db.all_(synced, "select * from content_projects where format='long'")
    shorts = db.all_(synced, "select * from content_projects where format='short'")
    assert len(longs) == 2 and len(shorts) == 4
    for p in longs + shorts:
        assert (Path(storage.root) / p["recipe"]["preview_key"]).exists()
    # roles were spread across different providers (writer != voice editor / critic / checker)
    writer = [p for r, p in router.calls if r == "scriptwriter"][0]
    assert all(p != writer for r, p in router.calls if r in ("voice_editor", "critic", "claim_checker"))
    for p in longs:  # per video: no check was made by a company that wrote or edited any of its text
        writers = set(p["quality_report"]["writers"])
        sv = db.one(synced, "select provider_trail from script_versions where id=%s", (p["current_script_version_id"],))
        checks = [t for t in sv["provider_trail"] if t["step"] in ("critic", "critic_recheck", "hook_pick")]
        assert writers and checks and all(not (set(t["companies"]) & writers) for t in checks)
    claims = db.all_(synced, "select status from research_claims")
    assert claims and all(c["status"] == "supported" for c in claims)
    money = next(p for p in longs if p["channel_slug"] == "money")
    desc = money["recipe"]["package"]["youtube_description"]
    assert "not personal" in desc.lower() and "[SOURCES]" not in desc and "https://example.org/money/" in desc
    assert db.one(synced, "select count(*) n from thumbnails")["n"] == 6
    posts = db.all_(synced, "select status from scheduled_posts")
    assert posts and all(p["status"] == "pending_approval" for p in posts)
    assert db.one(synced, "select count(*) n from notifications where kind='week_ready'")["n"] == 1


def test_provider_outage_falls_back_but_never_lets_a_writer_check_itself(synced, monkeypatch, silent_tts):
    router, _, _, out = _produce_week(synced, monkeypatch, failing={"alpha"})
    assert sum(1 for _, p in router.calls if p == "alpha") == 1  # circuit opened after the first quota error
    used = {p for r, p in router.calls if p != "alpha"}
    assert used >= {"beta", "gamma"}  # writing moved to the companies still working
    # beta wrote, gamma polished the voice: with alpha down nobody independent is left to critique, so the package
    # waits (and retries later) instead of letting a writer check its own work
    assert {p["status"] for p in out["projects"]} == {"retrying"}
    err = db.one(synced, "select error_message from generation_jobs where job_type='script' order by updated_at desc limit 1")
    assert "No independent AI available" in err["error_message"]


def test_failed_render_resumes_from_saved_stage(synced, monkeypatch, silent_tts):
    real = rendering.render
    state = {"fail": True}

    def flaky(*a, **kw):
        if state["fail"]:
            state["fail"] = False
            raise rendering.TransientError("ffmpeg crashed")
        return real(*a, **kw)

    monkeypatch.setattr("studio.media.render.render", flaky)
    router, storage, week, out = _produce_week(synced, monkeypatch)
    failed = db.all_(synced, "select * from generation_jobs where job_type='render_preview' and status='retrying'")
    assert len(failed) == 1
    script_calls = sum(1 for r, _ in router.calls if r == "scriptwriter")
    # resume: retry is due now
    db.run(synced, "update generation_jobs set next_attempt_at=now() where id=%s", (failed[0]["id"],))
    pid = failed[0]["project_id"]
    p = db.one(synced, "select * from content_projects where id=%s", (pid,))
    body = db.one(synced, "select body from script_versions where id=%s", (p["current_script_version_id"],))["body"]
    produce.render_preview(synced, storage, pid, body, p["channel_slug"], p["format"])
    produce.final_status(synced, pid)
    assert db.one(synced, "select status from content_projects where id=%s", (pid,))["status"] == "ready_for_review"
    assert sum(1 for r, _ in router.calls if r == "scriptwriter") == script_calls  # script not regenerated


# ----------------------------------------------------------------------------- publishing

class Platform:
    """Mock of YouTube / Facebook / TikTok / X HTTP APIs that records requests."""

    def __init__(self):
        self.requests = []

    def __call__(self, req: httpx.Request):
        self.requests.append((req.method, str(req.url)))
        u = str(req.url)
        if "upload/youtube/v3/videos" in u and req.method == "POST":
            return httpx.Response(200, headers={"location": "https://upload.example/session1"})
        if u.startswith("https://upload.example/session1"):
            return httpx.Response(200, json={"id": "yt123"})
        if "thumbnails/set" in u:
            return httpx.Response(200, json={})
        if "video_stories" in u:
            if "upload_phase=start" in req.content.decode():
                return httpx.Response(200, json={"video_id": "fbs1", "upload_url": "https://rupload.example/fbs1"})
            return httpx.Response(200, json={"success": True, "post_id": "page_story1"})
        if "graph-video.facebook.com" in u and u.endswith("/videos"):
            body = req.content.decode("latin-1")
            if "upload_phase=start" in body:
                self.video_size = int(body.split("file_size=")[1].split("&")[0])
                return httpx.Response(200, json={"upload_session_id": "sess1", "video_id": "fbv1", "start_offset": "0",
                                                 "end_offset": str(min(self.video_size, 1 << 20))})
            if 'name="upload_phase"\r\n\r\ntransfer' in body:
                start = int(body.split('name="start_offset"\r\n\r\n')[1].split("\r\n")[0])
                nxt = min(self.video_size, start + (1 << 20))
                return httpx.Response(200, json={"start_offset": str(nxt), "end_offset": str(min(self.video_size, nxt + (1 << 20)))})
            return httpx.Response(200, json={"success": True})
        if "video_reels" in u:
            body = req.content.decode()
            if "upload_phase=start" in body:
                return httpx.Response(200, json={"video_id": "fb999", "upload_url": "https://rupload.example/fb999"})
            return httpx.Response(200, json={"success": True})
        if "rupload.example" in u:
            return httpx.Response(200, json={"success": True})
        if "/feed" in u:
            return httpx.Response(200, json={"id": "page_post1"})
        if "inbox/video/init" in u:
            return httpx.Response(200, json={"data": {"publish_id": "tt1", "upload_url": "https://tt-upload.example/1"},
                                             "error": {"code": "ok"}})
        if "tt-upload.example" in u:
            return httpx.Response(201)
        if "api.x.com/2/tweets" in u:
            return httpx.Response(201, json={"data": {"id": "x42"}})
        return httpx.Response(404, json={"error": u})


def _connect_all(conn):
    for a in db.all_(conn, "select * from social_accounts"):
        tokens = {"access_token": "tok", "expires_at": 9e9, "refresh_token": "r"}
        if a["platform"] == "facebook":
            tokens = {"page_token": "ptok", "page_id": "123"}
        oauth.save(conn, a["id"], tokens)


def _approve_all(conn):
    owner = "00000000-0000-0000-0000-000000000001"
    for v in db.all_(conn, "select id, project_id from content_variants"):
        db.run(conn, "insert into approvals (target_type, target_id, decision, decided_by) values ('variant',%s,'approved',%s)",
               (v["id"], owner))
        db.run(conn, "update content_variants set status='approved' where id=%s", (v["id"],))
    # as approve_project does: the packages themselves are approved at their current script version
    db.run(conn, """insert into approvals (target_type, target_id, decision, script_version_id, decided_by)
                    select 'project', id, 'approved', current_script_version_id, %s from content_projects
                     where status in ('ready_for_review','needs_attention')""", (owner,))
    db.run(conn, """update content_projects set status='approved', approved_script_version_id=current_script_version_id
                    where status in ('ready_for_review','needs_attention')""")


def _adapters(platform):
    client = httpx.Client(transport=httpx.MockTransport(platform))
    return {"youtube": adapters.YouTube(client), "facebook": adapters.Facebook(client),
            "tiktok": adapters.TikTok(client), "x": adapters.X(client)}


@pytest.fixture()
def produced(synced, monkeypatch, silent_tts):
    _, storage, week, _ = _produce_week(synced, monkeypatch)
    return synced, storage


def test_journey_approval_schedule_publish_and_no_duplicates(produced):
    conn, storage = produced
    _connect_all(conn)
    far_future = datetime.now(timezone.utc) + timedelta(days=30)
    # nothing publishes before approval
    platform = Platform()
    assert runner.run_due(conn, storage, _adapters(platform), now=far_future) == {}
    _approve_all(conn)
    assert db.one(conn, "select count(*) n from scheduled_posts where status='scheduled'")["n"] > 0
    db.run(conn, "update content_projects set fresh_until = now() + interval '60 days'")
    result = runner.run_due(conn, storage, _adapters(platform), now=far_future)
    total = db.one(conn, "select count(*) n from scheduled_posts")["n"]
    assert sum(result.values()) == total
    pub = db.all_(conn, "select platform, method, visibility from published_posts")
    methods = {(p["platform"], p["method"]) for p in pub}
    assert ("youtube", "api_draft") in methods          # unaudited API -> private upload + manual follow-up
    assert ("tiktok", "api_draft") in methods           # unaudited -> inbox draft
    assert ("facebook", "api") in methods and ("x", "api") in methods
    assert db.one(conn, "select count(*) n from manual_tasks")["n"] >= 1
    # X spend recorded within budget
    spent = db.one(conn, "select coalesce(sum(amount_usd),0) s from budget_reservations where status='committed'")["s"]
    assert 0 < float(spent) <= 1.0
    # duplicate prevention is enforced by the database: a published post can't be put back in the queue, removed,
    # or rewritten, and nothing is sent again
    before = len(platform.requests)
    for sql in ("update scheduled_posts set status='scheduled', locked_until=null where status='published'",
                "delete from published_posts", "update published_posts set content_sha256='x'",
                "delete from publish_attempts", "update audit_logs set action='edited'", "delete from audit_logs"):
        with pytest.raises(psycopg.errors.RaiseException):
            db.run(conn, sql)
    again = runner.run_due(conn, storage, _adapters(platform), now=far_future)
    assert sum(again.values()) == 0 and len(platform.requests) == before
    assert db.one(conn, "select count(*) n from published_posts where content_sha256 is null and method <> 'manual'")["n"] == 0
    attempts = db.all_(conn, "select scheduled_post_id, social_account_id, content_sha256, outcome from publish_attempts")
    assert attempts and {a["outcome"] for a in attempts} <= {"published", "blocked_duplicate"}
    for a in attempts:  # the sample week has word-for-word identical X posts: the second one is stopped
        if a["outcome"] == "blocked_duplicate":
            assert db.one(conn, "select 1 from published_posts where social_account_id=%s and content_sha256=%s",
                          (a["social_account_id"], a["content_sha256"]))
    assert db.all_(conn, "select * from audit_chain_problems()") == []
    actions = {r["action"] for r in db.all_(conn, "select action from audit_logs")}
    assert {"publish_attempt_started", "published", "scheduled_posts_update", "content_projects_update"} <= actions


def test_expired_finance_data_blocks_publication(produced):
    conn, storage = produced
    _connect_all(conn)
    _approve_all(conn)
    db.run(conn, "update content_projects set fresh_until = now() - interval '1 day'")
    out = runner.run_due(conn, storage, _adapters(Platform()), now=datetime.now(timezone.utc) + timedelta(days=30))
    assert set(out) == {"blocked"}
    assert db.one(conn, "select count(*) n from published_posts")["n"] == 0
    assert "expired" in db.one(conn, "select last_error from scheduled_posts limit 1")["last_error"]


def test_budget_exhaustion_disables_x(produced):
    conn, storage = produced
    _connect_all(conn)
    _approve_all(conn)
    db.run(conn, "update content_projects set fresh_until = now() + interval '60 days'")
    db.run(conn, "update budgets set monthly_cap_usd = 0.01 where service='x_api'")
    platform = Platform()
    runner.run_due(conn, storage, _adapters(platform), now=datetime.now(timezone.utc) + timedelta(days=30))
    assert not any("api.x.com" in u for _, u in platform.requests)
    x_posts = db.all_(conn, """select sp.status from scheduled_posts sp join social_accounts a on a.id=sp.social_account_id
                               where a.platform='x'""")
    assert x_posts and all(p["status"] == "needs_manual" for p in x_posts)


def test_unconnected_platform_creates_manual_task(produced):
    conn, storage = produced
    _approve_all(conn)
    db.run(conn, "update content_projects set fresh_until = now() + interval '60 days'")
    out = runner.run_due(conn, storage, _adapters(Platform()), now=datetime.now(timezone.utc) + timedelta(days=30))
    assert set(out) == {"manual"}
    assert db.one(conn, "select count(*) n from published_posts")["n"] == 0
    assert db.one(conn, "select count(*) n from manual_tasks")["n"] == db.one(conn, "select count(*) n from scheduled_posts")["n"]


def test_x_blocks_links_to_protect_budget():
    x = adapters.X(httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(500))))
    with pytest.raises(adapters.PermanentError):
        x.cost_for("Read more at https://example.com")
    assert x.cost_for("No links here, just a thought.") == 0.015


def test_ambiguous_upload_goes_to_review_not_retry(produced):
    conn, storage = produced
    _connect_all(conn)
    _approve_all(conn)
    db.run(conn, "update content_projects set fresh_until = now() + interval '60 days'")

    def flaky(req):
        if req.url.host == "upload.example":
            raise httpx.ReadTimeout("dropped", request=req)
        return Platform()(req)

    runner.run_due(conn, storage, _adapters(flaky), now=datetime.now(timezone.utc) + timedelta(days=30))
    yt = db.all_(conn, """select sp.status from scheduled_posts sp join content_variants v on v.id=sp.variant_id
                          join social_accounts a on a.id=sp.social_account_id where a.platform='youtube'""")
    assert yt and all(p["status"] == "needs_review" for p in yt)
