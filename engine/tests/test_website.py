"""The public website: one article per approved, published video, built as plain files with no way into the studio."""

from datetime import datetime, timedelta, timezone

from studio import db, website
from studio.publish import runner

from .test_end_to_end import Platform, _adapters, _approve_all, _connect_all, produced, silent_tts  # noqa: F401


def _publish(conn, storage):
    _connect_all(conn)
    _approve_all(conn)
    db.run(conn, "update content_projects set fresh_until = now() + interval '60 days'")
    runner.run_due(conn, storage, _adapters(Platform()), now=datetime.now(timezone.utc) + timedelta(days=30))


def _heads(conn):
    return db.all_(conn, "select * from content_projects where parent_project_id is null order by created_at")


def test_nothing_appears_before_its_video_is_posted(produced, tmp_path):
    conn, storage = produced
    _approve_all(conn)
    articles, _ = website.collect(conn, storage, tmp_path / "work", check_video=lambda u: True)
    assert articles == []


def test_each_posted_video_becomes_an_article_and_the_site_has_no_way_into_the_studio(produced, tmp_path, monkeypatch):
    conn, storage = produced
    _publish(conn, storage)
    monkeypatch.setattr(website, "why_left_out", lambda c, p, b: None)   # this test is about the pages themselves
    articles, skipped = website.collect(conn, storage, tmp_path / "work", check_video=lambda u: True)
    assert articles and not skipped
    a = articles[0]
    assert a.paragraphs and a.video_id and a.image and (tmp_path / "work" / "images" / a.image).exists()
    out = tmp_path / "site"
    summary = website.build(articles, out, tmp_path / "work" / "images")
    assert summary["articles"] == len(articles)
    page = (out / "articles" / a.slug / "index.html").read_text()
    assert a.title.replace("'", "&#x27;").replace("&", "&amp;")[:20] in page or a.title[:20] in page
    assert "youtube-nocookie.com/embed/" + a.video_id in page and '"@type": "Article"' in page
    assert "Researched with AI tools" in page                                 # honest about how it's made
    for must in ("index.html", "ai/index.html", "money/index.html", "about/index.html", "privacy/index.html",
                 "affiliate-disclosure/index.html", "sitemap.xml", "robots.txt", "feed.xml", "404.html", "style.css"):
        assert (out / must).exists(), must
    assert f"/articles/{a.slug}/" in (out / "sitemap.xml").read_text()
    everything = " ".join(p.read_text(errors="ignore") for p in out.rglob("*") if p.is_file() and p.suffix != ".jpg")
    for secret_or_door in ("vercel.app", "supabase", "dashboard", "/settings", "SUPABASE", "service_role"):
        assert secret_or_door not in everything, secret_or_door


def test_unbacked_or_sensitive_packages_are_left_out_with_a_reason(produced, tmp_path):
    conn, storage = produced
    _publish(conn, storage)
    ai, money = (next(p for p in _heads(conn) if p["channel_slug"] == ch) for ch in ("ai", "money"))
    db.run(conn, "update research_claims set status='unsupported' where script_version_id=%s", (ai["current_script_version_id"],))
    db.run(conn, "update content_projects set title='Roth IRA vs 401(k): which first?' where id=%s", (money["id"],))
    articles, skipped = website.collect(conn, storage, tmp_path / "work", check_video=lambda u: True)
    ids = {a.project_id for a in articles}
    assert str(ai["id"]) not in ids and str(money["id"]) not in ids
    assert any("not backed by a source" in s for s in skipped) and any("sensitive money topic" in s for s in skipped)


def test_a_private_video_is_not_embedded(produced, tmp_path, monkeypatch):
    conn, storage = produced
    _publish(conn, storage)
    monkeypatch.setattr(website, "why_left_out", lambda c, p, b: None)
    articles, _ = website.collect(conn, storage, tmp_path / "work", check_video=lambda u: False)
    a = articles[0]
    assert a.video_id is None
    page = website.article_html(a)
    assert "youtube-nocookie" not in page and f"/images/{a.image}" in page


def test_addresses_stay_the_same_and_text_is_escaped():
    assert website.slugify("AI & You: 5 Tips!", "1234abcd-0000") == website.slugify("AI & You: 5 Tips!", "1234abcd-0000")
    assert website.slugify("AI & You: 5 Tips!", "1234abcd-0000") == "ai-you-5-tips-1234ab"
    a = website.Article("p1", "ai", "x-1", "<script>alert(1)</script>", "d", ["<b>hi</b>"], datetime(2026, 11, 8, tzinfo=timezone.utc))
    page = website.article_html(a)
    assert "<script>alert(1)</script>" not in page and "&lt;b&gt;hi&lt;/b&gt;" in page


# ------------------------------------------------------------------ found on the real "robots.txt" script (8 Nov)

REAL = {"title": "Can robots.txt Stop AI Training? Live Test with OpenAI's Signal",
        "hook": "I just added a new AI-training directive to a test site — here's what happened.",
        "scenes": [
            {"narration": "A study found that AI Overviews cut referrals nearly in half as of November 2025. Users clicked links "
                          "on pages with AI Overviews only 8% of the time as of November 2025, compared to 15% without them."},
            {"narration": "In this video, you will learn how website owners can control AI training on their website using "
                          "robots.txt, a simple text file that tells web crawlers which pages they can visit, as described in the passage."},
            {"narration": "Engineers introduced it in 1994 to set crawl permissions."},
            {"narration": "A study by the Pew Research Center found that AI Overviews cut referrals nearly in half (as of November 2025). "
                          "Users clicked links on pages with AI Overviews only 8% of the time, compared to 15% without (as of November 2025)."},
            {"narration": "In our live test, we will use a website with the shared robots.txt signal set to opt out of training."},
        ]}


def test_video_talk_invented_tests_and_repeats_are_removed_from_the_article():
    text = " ".join(website.article_paragraphs(REAL))
    assert "In this video" not in text and "passage" not in text           # video-only lines and instruction leftovers
    assert "test site" not in text and "live test" not in text             # no hands-on test that didn't happen
    assert text.count("8%") == 1                                           # the key number is said once
    assert "1994" in text                                                  # real content stays


def test_a_package_whose_title_or_opening_claims_a_test_is_left_out(produced):
    conn, _ = produced
    p = {"title": REAL["title"], "channel_slug": "ai", "quality_report": {}, "sv_id": None}
    assert website.why_left_out(conn, p, REAL) == "claims a hands-on test that didn't happen"
