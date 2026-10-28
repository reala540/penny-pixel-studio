"""The Performance page's numbers: read-only from YouTube Analytics (faked here), missing numbers recorded as
missing (never zero), and what each package cost."""

import uuid
from datetime import date

import httpx

from studio import analytics, capacity, db

from .test_database import as_user, reset_role
from .test_end_to_end import _connect_all


def _published_youtube_post(c, video_id="yt1", title="AI ROI Reality"):
    acc = db.one(c, "select id from social_accounts where platform='youtube' order by label limit 1")["id"]
    pid = db.one(c, "insert into content_projects (channel_slug, format, title, status) values ('ai','long','AI ROI','published') returning id")["id"]
    v = db.one(c, "insert into content_variants (project_id, social_account_id, kind, title, status) values (%s,%s,'long_video',%s,'published') returning id",
               (pid, acc, title))["id"]
    sp = db.one(c, """insert into scheduled_posts (variant_id, social_account_id, scheduled_at, status, idempotency_key)
                      values (%s,%s,now() - interval '3 days','published',%s) returning id""", (v, acc, f"post:{v}"))["id"]
    pp = db.one(c, """insert into published_posts (scheduled_post_id, platform, platform_post_id, url, visibility, method, social_account_id, published_at)
                      values (%s,'youtube',%s,'https://youtu.be/x','public','api',%s, now() - interval '3 days') returning id""", (sp, video_id, acc))["id"]
    return pid, pp


class FakeAnalytics:
    def __init__(self, extras_fail=("videoThumbnailImpressions", "estimatedRevenue")):
        self.calls, self.extras_fail = [], extras_fail

    def __call__(self, req):
        q = dict(req.url.params)
        self.calls.append(q)
        assert req.method == "GET"                       # read-only
        metrics = q["metrics"].split(",")
        if any(m in metrics[0] for m in self.extras_fail):
            return httpx.Response(400, json={"error": {"message": "not available"}})
        if q.get("dimensions") == "video":
            return httpx.Response(200, json={"columnHeaders": [{"name": "video"}] + [{"name": m} for m in metrics],
                                             "rows": [["yt1", *[10 * (i + 1) for i in range(len(metrics))]]]})
        if q.get("dimensions") == "country":
            return httpx.Response(200, json={"columnHeaders": [{"name": "country"}, {"name": "views"}], "rows": [["US", 70], ["GB", 12]]})
        return httpx.Response(200, json={"columnHeaders": [{"name": m} for m in metrics], "rows": [[500, 900, 4]]})


def test_youtube_numbers_are_collected_and_missing_ones_say_so(synced, monkeypatch):
    c = synced
    _connect_all(c)
    _, pp = _published_youtube_post(c)
    fake = FakeAnalytics()
    out = analytics.collect(c, httpx.Client(transport=httpx.MockTransport(fake)), today=date(2026, 10, 30))
    assert any(o.get("posts") == 1 for o in out), out
    m = db.one(c, "select * from post_metrics where published_post_id=%s", (pp,))
    assert m["views"] == 10 and m["watch_minutes"] == 20 and m["avg_view_seconds"] == 30
    assert m["impressions"] is None and m["ctr"] is None and m["revenue_usd"] is None   # not given: empty, not zero
    assert {"impressions", "ctr", "revenue_usd"} <= set(m["missing"])
    acct = db.one(c, "select * from account_metrics where views=500")
    assert acct["top_countries"][0] == {"country": "US", "views": 70}
    # collecting again the same day updates, never duplicates
    analytics.collect(c, httpx.Client(transport=httpx.MockTransport(fake)), today=date(2026, 10, 30))
    assert db.one(c, "select count(*) n from post_metrics where published_post_id=%s", (pp,))["n"] == 1


def test_a_failing_channel_doesnt_stop_the_others(synced):
    c = synced
    _connect_all(c)
    _published_youtube_post(c)
    out = analytics.collect(c, httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(500))), today=date(2026, 10, 30))
    by = {o["account"]: o for o in out}
    assert by["YouTube AI"]["error"] == "HTTPStatusError"                       # this one failed and says so
    assert by["YouTube Money"]["missing"] == ["totals", "countries"]           # the other still ran


def test_owner_reads_performance_and_costs(synced):
    c = synced
    _connect_all(c)
    pid, pp = _published_youtube_post(c)
    db.run(c, "insert into post_metrics (published_post_id, collected_on, views, missing, source) values (%s, current_date, 42, '{}', 'test')", (pp,))
    capacity.record_render(c, pid, "final", 120.0, 600.0, 1000)
    as_user(c, str(uuid.uuid4()))
    db.one(c, "select public.claim_ownership() ok")
    rows = db.all_(c, "select * from public.studio_performance(90)")
    costs = db.all_(c, "select * from public.studio_package_costs(90)")
    reset_role(c)
    assert rows[0]["views"] == 42 and rows[0]["title"] == "AI ROI Reality" and rows[0]["platform"] == "youtube"
    cost = next(x for x in costs if x["project_id"] == pid)
    assert float(cost["render_minutes"]) == 2.0 and float(cost["x_spend_usd"]) == 0


def test_strangers_cant_read_performance(synced):
    c = synced
    as_user(c, str(uuid.uuid4()))          # signed in, but not the owner
    import psycopg
    import pytest
    with pytest.raises(psycopg.errors.RaiseException):
        db.all_(c, "select * from public.studio_performance(90)")
    reset_role(c)
