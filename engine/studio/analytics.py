"""Read-only performance numbers for the Performance page, collected once a day.

YouTube: per-video views, watch time, average view duration, likes, comments, shares, subscribers gained, and (when
YouTube provides them) impressions, click-through rate and revenue; per channel, the top countries of the last 28
days. Any number YouTube doesn't return is recorded as missing, never as zero. Facebook, TikTok and X are not read
yet (Facebook needs the Page insights permission; X charges for reading stats), so the page says so.
Nothing here posts, approves or spends anything.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import httpx

from . import db, oauth

API = "https://youtubeanalytics.googleapis.com/v2/reports"
BASE = ["views", "estimatedMinutesWatched", "averageViewDuration", "likes", "comments", "shares", "subscribersGained"]
EXTRA = {"impressions": ["videoThumbnailImpressions", "videoThumbnailImpressionsClickRate"],
         "revenue": ["estimatedRevenue"]}
COLUMN = {"views": "views", "estimatedMinutesWatched": "watch_minutes", "averageViewDuration": "avg_view_seconds",
          "likes": "likes", "comments": "comments", "shares": "shares", "subscribersGained": "subscribers_gained",
          "videoThumbnailImpressions": "impressions", "videoThumbnailImpressionsClickRate": "ctr",
          "estimatedRevenue": "revenue_usd"}


def _report(client: httpx.Client, token: str, metrics: list[str], start: date, end: date, **params) -> dict:
    r = client.get(API, headers={"Authorization": f"Bearer {token}"}, params={
        "ids": "channel==MINE", "startDate": start.isoformat(), "endDate": end.isoformat(),
        "metrics": ",".join(metrics), **params})
    r.raise_for_status()
    body = r.json()
    names = [h["name"] for h in body.get("columnHeaders") or []]
    return {"names": names, "rows": body.get("rows") or []}


def _by_video(rep: dict) -> dict[str, dict]:
    out = {}
    for row in rep["rows"]:
        rec = dict(zip(rep["names"], row))
        out[str(rec.pop("video"))] = rec
    return out


def collect_youtube(conn, account: dict, client: httpx.Client, today: date) -> dict:
    """One channel's numbers, written as today's rows. Returns a small summary for the maintenance log."""
    posts = db.all_(conn, """select pp.id, pp.platform_post_id, pp.published_at from published_posts pp
                             join scheduled_posts sp on sp.id = pp.scheduled_post_id
                            where sp.social_account_id=%s and pp.platform='youtube' and pp.platform_post_id is not null
                              and pp.published_at > now() - interval '180 days'""", (account["id"],))
    token, _ = oauth.access_token(conn, account)
    written = 0
    if posts:
        start = min(p["published_at"] for p in posts).date()
        ids = [p["platform_post_id"] for p in posts]
        numbers: dict[str, dict] = {}
        missing_all: set[str] = set()
        for i in range(0, len(ids), 50):  # YouTube accepts a limited number of videos per filter
            batch = ids[i:i + 50]
            params = {"dimensions": "video", "filters": "video==" + ",".join(batch), "maxResults": 200}
            for vid, rec in _by_video(_report(client, token, BASE, start, today, **params)).items():
                numbers.setdefault(vid, {}).update(rec)
            for label, metrics in EXTRA.items():
                try:
                    for vid, rec in _by_video(_report(client, token, metrics, start, today, **params)).items():
                        numbers.setdefault(vid, {}).update(rec)
                except httpx.HTTPError:  # not available for this channel yet (e.g. revenue before monetisation)
                    missing_all.update(COLUMN[m] for m in metrics)
        for p in posts:
            rec = numbers.get(p["platform_post_id"])
            values = {COLUMN[k]: v for k, v in (rec or {}).items() if k in COLUMN}
            missing = sorted((set(COLUMN.values()) - set(values)) | missing_all) if rec else ["all (no data from YouTube yet)"]
            cols = list(COLUMN.values())
            db.run(conn, f"""insert into post_metrics (published_post_id, collected_on, {", ".join(cols)}, missing, source)
                             values (%s, %s, {", ".join(["%s"] * len(cols))}, %s, 'youtube_analytics')
                             on conflict (published_post_id, collected_on) do update set
                             {", ".join(f"{c}=excluded.{c}" for c in cols)}, missing=excluded.missing""",
                   (p["id"], today, *[values.get(c) for c in cols], missing))
            written += 1
    # the channel as a whole: the last 28 days and where viewers are
    start28 = today - timedelta(days=28)
    missing: list[str] = []
    total = {}
    try:
        t = _report(client, token, ["views", "estimatedMinutesWatched", "subscribersGained"], start28, today)
        total = dict(zip(t["names"], t["rows"][0])) if t["rows"] else {}
    except httpx.HTTPError:
        missing.append("totals")
    countries = []
    try:
        c = _report(client, token, ["views"], start28, today, dimensions="country", sort="-views", maxResults=10)
        countries = [{"country": row[0], "views": row[1]} for row in c["rows"]]
    except httpx.HTTPError:
        missing.append("countries")
    db.run(conn, """insert into account_metrics (social_account_id, collected_on, period_days, views, watch_minutes,
                                                 subscribers_gained, top_countries, missing, note, source)
                    values (%s,%s,28,%s,%s,%s,%s,%s,%s,'youtube_analytics')
                    on conflict (social_account_id, collected_on) do update set views=excluded.views,
                      watch_minutes=excluded.watch_minutes, subscribers_gained=excluded.subscribers_gained,
                      top_countries=excluded.top_countries, missing=excluded.missing, note=excluded.note""",
           (account["id"], today, total.get("views"), total.get("estimatedMinutesWatched"), total.get("subscribersGained"),
            db.j(countries), missing, "YouTube's numbers arrive one to three days late"))
    return {"account": account["label"], "posts": written, "missing": missing}


def collect(conn, client: httpx.Client | None = None, today: date | None = None) -> list[dict]:
    """Every connected YouTube channel. A problem with one channel never stops the others or maintenance."""
    if not db.one(conn, "select 1 from information_schema.tables where table_schema='public' and table_name='post_metrics'"):
        return [{"skipped": "the Performance tables aren't there yet (run the latest database update)"}]
    client = client or httpx.Client(timeout=30)
    today = today or datetime.now(timezone.utc).date()
    out = []
    for acc in db.all_(conn, """select a.* from social_accounts a join oauth_connections c on c.social_account_id=a.id
                                where a.platform='youtube' and c.status='connected'"""):
        try:
            out.append(collect_youtube(conn, acc, client, today))
        except Exception as exc:  # noqa: BLE001
            out.append({"account": acc["label"], "error": type(exc).__name__})
    return out
