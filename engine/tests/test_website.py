"""The public website: one article per approved, published video, built as plain files with no way into the studio."""

import json
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
    monkeypatch.setattr(website, "DUPLICATE_TITLE", 1.1)                   # the fake packages share one title
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
    assert "researched with AI tools" in page                                 # honest about how it's made
    for must in ("index.html", "latest/index.html", f"{a.channel}/index.html", "about/index.html", "privacy/index.html",
                 "terms/index.html", "contact/index.html", "editorial-policy/index.html", "ai-content-policy/index.html",
                 "corrections/index.html", "advertise/index.html", "affiliate-disclosure/index.html", "search/index.html",
                 "videos/index.html", "search-index.json", "sitemap.xml", "robots.txt", "feed.xml", "404.html",
                 "assets/site.css", "assets/site.js", "favicon.svg", "icon-512.png", "og-default.png", "_headers"):
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


def test_the_feed_and_sitemap_are_valid_xml(tmp_path):
    """Found on 8 Nov: the RSS feed wouldn't open ('xmlParseEntityRef: no name') because of the bare & in the name."""
    import xml.etree.ElementTree as ET

    a = website.Article("p1", "money", "pay-1", "Pay & prices: what changed", "Wages & inflation", ["Text & more."],
                        datetime(2026, 11, 8, tzinfo=timezone.utc))
    website.build([a], tmp_path / "site")
    for name in ("feed.xml", "sitemap.xml"):
        ET.parse(tmp_path / "site" / name)                                  # raises if the file isn't valid XML
    assert ET.parse(tmp_path / "site" / "feed.xml").find("channel/title").text == "Penny & Pixel"
    page = (tmp_path / "site" / "articles" / "pay-1" / "index.html").read_text()
    assert "<title>Pay &amp; prices: what changed · Penny &amp; Pixel</title>" in page and "&amp;amp;" not in page



# ------------------------------------------------------------------ the redesigned site (8 Nov)

def _art(slug, channel="ai", title=None, days=0, **kw):
    return website.Article(slug, channel, slug, title or f"Article {slug}", "A description.", ["One paragraph of text."] * 3,
                           datetime(2026, 11, 8, tzinfo=timezone.utc) - timedelta(days=days), **kw)


def test_title_cards_become_section_headings_with_a_contents_list():
    body = {"scenes": [
        {"visual": {"type": "title_card", "headline": "What You'll Learn"}, "narration": "Today we cover three things you can use."},
        {"visual": {"type": "title_card", "headline": "Understanding the Issue"}, "narration": "Prices rose 0.6% in September 2026, according to the BLS."},
        {"visual": {"type": "stat"}, "narration": "That matters for every household budget across the country this year."},
        {"visual": {"type": "title_card", "headline": "Inflation and Unemployment Trends"}, "narration": "Unemployment was 4.2% in September 2026."},
        {"visual": {"type": "title_card", "headline": "Limits of the Minimum Wage"}, "narration": "Minimum wage alone is a narrow yardstick for fair pay."},
    ]}
    blocks = website.article_blocks(body)
    heads = [t for k, t in blocks if k == "h2"]
    assert heads == ["Understanding the Issue", "Inflation and Unemployment Trends", "Limits of the Minimum Wage"]
    a = _art("x", blocks=blocks)
    page = website.article_html(a)
    assert "In this article" in page and 'href="#s' in page                  # a contents list for 3+ sections


def test_only_real_sections_appear_and_pages_carry_no_inline_code(tmp_path):
    out = tmp_path / "site"
    website.build([_art("a1", "ai")], out, socials=[], options={})
    home = (out / "index.html").read_text()
    assert 'href="/ai/"' in home and 'href="/money/"' not in home            # no empty Money category
    assert not (out / "money").exists() and not (out / "videos").exists()   # no Videos page without real videos
    assert "Get new guides by email" not in home                             # no newsletter until a provider is set
    for page in out.rglob("*.html"):
        text = page.read_text()
        assert 'style="' not in text and "onclick" not in text, page        # the security policy allows no inline code
    headers = (out / "_headers").read_text()
    assert "Content-Security-Policy:" in headers and "frame-ancestors 'none'" in headers
    index = json.loads((out / "search-index.json").read_text())
    assert index[0]["u"] == "/articles/a1/" and index[0]["c"] == "AI tools"


def test_a_newsletter_appears_only_with_a_configured_provider(tmp_path):
    out = tmp_path / "site"
    website.build([_art("a1")], out, options={"newsletter": {"form_action": "https://buttondown.com/api/emails/embed-subscribe/pp",
                                                             "provider": "Buttondown"}})
    home = (out / "index.html").read_text()
    assert "Get new guides by email" in home and 'type="checkbox" required' in home   # consent is required
    assert "form-action 'self' https://buttondown.com" in (out / "_headers").read_text()


def test_owner_can_take_an_article_off_the_website(produced, tmp_path, monkeypatch):
    conn, storage = produced
    _publish(conn, storage)
    monkeypatch.setattr(website, "why_left_out", lambda c, p, b: None)
    first, _ = website.collect(conn, storage, tmp_path / "w1", check_video=lambda u: True)
    gone = first[0].project_id
    db.run(conn, "insert into settings (key, value) values ('website_hidden', %s) on conflict (key) do update set value=excluded.value",
           (db.j({"hidden": {gone: True}}),))
    again, skipped = website.collect(conn, storage, tmp_path / "w2", check_video=lambda u: True)
    assert gone not in {a.project_id for a in again} and any("taken off the website by you" in s for s in skipped)


def test_near_duplicate_titles_keep_only_the_first(produced, tmp_path, monkeypatch):
    conn, storage = produced
    _publish(conn, storage)
    monkeypatch.setattr(website, "why_left_out", lambda c, p, b: None)
    monkeypatch.setattr(website, "_title_words", lambda t: {"inflation", "changes", "paycheck"})   # every title alike
    articles, skipped = website.collect(conn, storage, tmp_path / "w", check_video=lambda u: True)
    assert len(articles) == 1 and any("too similar to an article already on the website" in s for s in skipped)


# ------------------------------------------------------------------ AI rewrite and German version (8 Nov)

from studio.website import enhance  # noqa: E402

SRC = [("p", "Prices rose 0.6% in September 2026, according to the Bureau of Labor Statistics. Prices rose 0.6% that month."),
       ("p", "Unemployment was 4.2% in September 2026. ChatGPT and Google Sheets can help you track your own budget."),
       ("p", "Average hourly earnings went up by $0.05 that month, so real pay barely moved for many workers.")]


def test_a_rewrite_with_a_new_number_or_name_is_not_used():
    good = [("p", "In September 2026, prices rose 0.6%, according to the Bureau of Labor Statistics."),
            ("h2", "Jobs and pay"), ("p", "Unemployment was 4.2% that month, and average hourly earnings went up by $0.05."),
            ("p", "So real pay barely moved for many workers. ChatGPT and Google Sheets can help you track your own budget.")]
    assert enhance.check_rewrite(SRC, good) is None
    assert "new numbers" in enhance.check_rewrite(SRC, good + [("p", "Experts expect 3% next year.")])
    assert "new names" in enhance.check_rewrite(SRC, [("p", t.replace("ChatGPT", "Microsoft Copilot")) if k == "p" else (k, t) for k, t in good])
    assert "forbidden wording" in enhance.check_rewrite(SRC, good + [("p", "In this video we tested it ourselves.")])
    assert "length" in enhance.check_rewrite(SRC, good[:1])


def test_a_translation_must_keep_every_number_and_name():
    de = [("p", "Im September 2026 stiegen die Preise um 0,6 %, so das Bureau of Labor Statistics. Die Preise stiegen in dem Monat um 0,6 %."),
          ("p", "Die Arbeitslosenquote lag im September 2026 bei 4,2 %. ChatGPT und Google Sheets helfen Ihnen, Ihr eigenes Budget zu verfolgen."),
          ("p", "Die durchschnittlichen Stundenlöhne stiegen in dem Monat um $0,05, daher bewegte sich der Reallohn für viele kaum.")]
    assert enhance.check_translation(SRC, de) is None
    wrong = [(k, t.replace("4,2", "4,3")) for k, t in de]
    assert "numbers differ" in enhance.check_translation(SRC, wrong)
    lost = [(k, t.replace("ChatGPT und Google Sheets helfen", "Werkzeuge helfen")) for k, t in de]
    assert "names lost" in enhance.check_translation(SRC, lost)


class _Router:
    def __init__(self, answers):
        self.answers, self.calls = answers, 0

    def complete(self, role, prompt, schema=None, **kw):
        from types import SimpleNamespace

        self.calls += 1
        answer = {"faithful":True,"issues":[]} if schema is enhance.MeaningReview else self.answers.pop(0)
        return SimpleNamespace(data=schema.model_validate(answer))


def test_the_ai_steps_run_once_per_version_and_money_stays_english(tmp_path):
    from studio.storage import LocalStorage

    storage = LocalStorage(tmp_path / "store")
    draft = {"intro": SRC[0][1], "sections": [{"heading": "Jobs and pay", "paragraphs": [SRC[1][1], SRC[2][1]]}]}
    german = {"title": "Preise und Löhne", "intro": "Im September 2026 stiegen die Preise um 0,6 %, so das Bureau of Labor Statistics. Die Preise stiegen um 0,6 %.",
              "sections": [{"heading": "Arbeit und Lohn", "paragraphs": [
                  "Die Arbeitslosenquote lag im September 2026 bei 4,2 %. ChatGPT und Google Sheets helfen Ihnen, Ihr Budget zu verfolgen.",
                  "Die durchschnittlichen Stundenlöhne stiegen um $0,05, daher bewegte sich der Reallohn für viele Beschäftigte kaum."]}]}
    r = _Router([draft, german])
    got = enhance.enhance(r, storage, "sv-1", "Prices and pay", "ai", SRC, tmp_path / "w")
    assert got["en"] and got["de"]["title"] == "Preise und Löhne" and r.calls == 4
    again = enhance.enhance(_Router([]), storage, "sv-1", "Prices and pay", "ai", SRC, tmp_path / "w2")
    assert again == json.loads(json.dumps(got))                              # cached: no new AI call
    money = enhance.enhance(_Router([draft]), storage, "sv-2", "Prices and pay", "money", SRC, tmp_path / "w3")
    assert money["de"] is None and "stay in English" in money["de_note"]


def test_no_free_ai_service_means_no_cache_and_the_plain_version(tmp_path):
    from studio.errors import TransientError
    from studio.storage import LocalStorage

    class Busy:
        def complete(self, *a, **k):
            raise TransientError("all busy")

    storage = LocalStorage(tmp_path / "store")
    got = enhance.enhance(Busy(), storage, "sv-9", "T", "ai", SRC, tmp_path / "w")
    assert got["en"] is None and "no free AI service" in got["en_note"]
    assert enhance.load(storage, "sv-9", tmp_path / "w") is None              # tried again next build


def test_german_pages_pair_with_their_english_originals(tmp_path):
    a = _art("a1", "ai", title="Prices and pay", de_title="Preise und Löhne",
             de_blocks=[("p", "Ein Absatz auf Deutsch.")] * 3)
    out = tmp_path / "site"
    website.build([a, _art("m1", "money")], out, options={"google_site_verification": "abc123"})
    en = (out / "articles" / "a1" / "index.html").read_text()
    de = (out / "de" / "artikel" / "a1" / "index.html").read_text()
    assert '<html lang="de">' in de and "Automatisch aus dem Englischen übersetzt" in de
    for page in (en, de):
        assert 'hreflang="de" href="https://pennyandpixel.pages.dev/de/artikel/a1/"' in page
        assert 'hreflang="en" href="https://pennyandpixel.pages.dev/articles/a1/"' in page
    assert "Auf Deutsch lesen" in en and not (out / "de" / "artikel" / "m1").exists()
    assert '<meta name="google-site-verification" content="abc123">' in (out / "index.html").read_text()
    assert "/de/artikel/a1/" in (out / "sitemap.xml").read_text()
