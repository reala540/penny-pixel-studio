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


MIN_POSTS_FOR_HINTS = 5


def packaging_hints(conn, channel: str) -> str:
    """What has worked on this channel so far, from real YouTube numbers, for the package writer. Empty until there
    are enough videos with numbers to compare (one or two posts tell you nothing)."""
    if not db.one(conn, "select 1 from information_schema.tables where table_schema='public' and table_name='post_metrics'"):
        return ""
    rows = db.all_(conn, """select distinct on (pp.id) coalesce(v.title, p.title) title, m.views, m.avg_view_seconds, m.ctr
                              from post_metrics m join published_posts pp on pp.id = m.published_post_id
                              join scheduled_posts sp on sp.id = pp.scheduled_post_id
                              join content_variants v on v.id = sp.variant_id
                              join content_projects p on p.id = v.project_id
                             where pp.platform='youtube' and p.channel_slug=%s and m.views is not null
                             order by pp.id, m.collected_on desc""", (channel,))
    if len(rows) < MIN_POSTS_FOR_HINTS:
        return ""
    rows.sort(key=lambda r: r["views"], reverse=True)
    top, bottom = rows[:3], rows[-3:]

    def line(r):
        extra = f", {float(r['ctr']):.1f}% click-through" if r.get("ctr") is not None else ""
        return f'- "{r["title"]}": {int(r["views"])} views{extra}'
    return ("Titles that did best so far:\n" + "\n".join(line(r) for r in top) + "\nTitles that did least well:\n"
            + "\n".join(line(r) for r in bottom) + f"\n(Based on {len(rows)} videos. Learn from the pattern, don't copy titles, "
            "and never make a title less accurate to chase clicks.)")


BOOST_MIN_VIEWS = 100


def boost_suggestions(conn) -> list[dict]:
    """Packages whose YouTube video is clearly beating this channel's usual views, while their Facebook post is
    recent: worth boosting on Facebook. Only a suggestion; the studio never spends money."""
    if not db.one(conn, "select 1 from information_schema.tables where table_schema='public' and table_name='post_metrics'"):
        return []
    rows = db.all_(conn, """select distinct on (pp.id) pp.id, coalesce(p.parent_project_id, p.id) project_id, p.channel_slug,
                                   coalesce(v.title, p.title) title, m.views
                              from post_metrics m join published_posts pp on pp.id = m.published_post_id
                              join scheduled_posts sp on sp.id = pp.scheduled_post_id
                              join content_variants v on v.id = sp.variant_id
                              join content_projects p on p.id = v.project_id
                             where pp.platform='youtube' and m.views is not null and pp.published_at > now() - interval '60 days'
                             order by pp.id, m.collected_on desc""")
    out = []
    for ch in {r["channel_slug"] for r in rows}:
        mine = sorted(r["views"] for r in rows if r["channel_slug"] == ch)
        if len(mine) < MIN_POSTS_FOR_HINTS:
            continue
        median = mine[len(mine) // 2]
        for r in rows:
            if r["channel_slug"] != ch or r["views"] < max(BOOST_MIN_VIEWS, 2 * median):
                continue
            fb = db.one(conn, """select pp.url, pp.published_at from published_posts pp
                                  join scheduled_posts sp on sp.id = pp.scheduled_post_id
                                  join content_variants v on v.id = sp.variant_id
                                  join content_projects p on p.id = v.project_id
                                 where pp.platform='facebook' and coalesce(p.parent_project_id, p.id)=%s
                                   and pp.published_at > now() - interval '7 days'
                                 order by pp.published_at desc limit 1""", (r["project_id"],))
            if fb:
                out.append({"project_id": str(r["project_id"]), "title": r["title"], "views": int(r["views"]),
                            "usual": int(median), "facebook_url": fb["url"]})
    return out


def notify_boosts(conn) -> int:
    from . import links, notify

    sent = 0
    for s in boost_suggestions(conn):
        notify.send(conn, "boost_suggestion", f"Worth boosting: {s['title'][:80]}",
                    f"Its YouTube video has {s['views']} views, about {s['views'] // max(s['usual'], 1)}x this channel's usual "
                    f"{s['usual']}. If you'd like more reach, open its Facebook post and press Boost with a budget you choose. "
                    "The studio never spends money.", link=s["facebook_url"] or links.project(s["project_id"]),
                    dedupe_key=f"boost:{s['project_id']}")
        sent += 1
    return sent
