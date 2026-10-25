"""Launch dates (nothing from a channel goes out before its day) and the channels' target countries."""

from datetime import datetime, timedelta, timezone

from studio import config, db
from studio.publish import runner
from studio.research import sources
from studio.script import pipeline

from .test_end_to_end import Platform, _adapters, _approve_all, _connect_all, _produce_week, silent_tts  # noqa: F401


def test_nothing_from_a_channel_is_scheduled_or_posted_before_its_launch_day(synced, monkeypatch, silent_tts):
    launch = (datetime.now(timezone.utc) + timedelta(days=20)).date()
    db.run(synced, "update channel_profiles set launch_date=%s where slug='money'", (launch,))
    router, storage, week, out = _produce_week(synced, monkeypatch)
    posts = db.all_(synced, """select p.channel_slug, sp.scheduled_at, sp.id, a.platform from scheduled_posts sp
                               join content_variants v on v.id = sp.variant_id join content_projects p on p.id = v.project_id
                               join social_accounts a on a.id = sp.social_account_id""")
    start = datetime.combine(launch, datetime.min.time(), tzinfo=timezone.utc) - timedelta(hours=3)  # Nairobi midnight
    assert any(p["channel_slug"] == "ai" for p in posts)  # Pixel is live: its posts are planned
    assert all(p["scheduled_at"] >= start for p in posts if p["channel_slug"] == "money")
    # even a money post forced into the past is held by the publisher, not sent
    _connect_all(synced)
    _approve_all(synced)
    ai_posts = [p for p in posts if p["channel_slug"] == "ai"]
    db.run(synced, "update content_projects set fresh_until = now() + interval '90 days'")
    project = db.one(synced, "select * from content_projects where channel_slug='money' and format='long' limit 1")
    acc = db.one(synced, "select * from social_accounts where label='YouTube Money'")
    v = db.one(synced, """insert into content_variants (project_id, social_account_id, kind, title, body, status)
                          values (%s,%s,'long_video','t','b','approved') returning id""", (project["id"], acc["id"]))
    db.run(synced, "insert into approvals (target_type, target_id, decision, decided_by) values ('variant',%s,'approved',%s)",
           (v["id"], "00000000-0000-0000-0000-000000000001"))
    forced = db.one(synced, """insert into scheduled_posts (variant_id, social_account_id, scheduled_at, status, idempotency_key)
                               values (%s,%s,now() - interval '1 hour','scheduled','forced') returning *""", (v["id"], acc["id"]))
    platform = Platform()
    assert runner.publish_post(synced, storage, forced, _adapters(platform)) == "not_launched"
    assert platform.requests == []
    assert ai_posts


def test_trending_searches_count_only_when_they_fit_a_channel():
    feed = """<rss xmlns:ht="https://trends.google.com/trending/rss"><channel>
      <item><title>chelsea vs tottenham</title><ht:approx_traffic>500K+</ht:approx_traffic></item>
      <item><title>weather</title><ht:approx_traffic>200K+</ht:approx_traffic></item>
      <item><title>chatgpt</title><ht:approx_traffic>100K+</ht:approx_traffic></item>
      <item><title>mortgage rates</title><ht:approx_traffic>50K+</ht:approx_traffic></item>
    </channel></rss>"""

    class F:
        def get(self, url, **kw):
            return type("R", (), {"text": feed})()

    items = sources.google_trends(F(), {"geo": ["US"]})
    assert sorted((i.metrics["term"], i.topic) for i in items) == [("chatgpt", "ai"), ("mortgage rates", "money")]
    assert len(sources.google_trends(F(), {"geo": ["US"], "keep_off_topic": True})) == 4


def test_scripts_are_written_for_each_channels_markets():
    ai, money = pipeline.voice_brief("ai"), pipeline.voice_brief("money")
    assert "US, GB, CA, AU, DE, NL" in ai and "American English" in ai
    assert "US, CA, GB, AU, CH, SG" in money and "401(k)" in money and "RRSP" in money
    assert config.brand()["channels"]["money"]["launch_date"] == "2026-11-01"
