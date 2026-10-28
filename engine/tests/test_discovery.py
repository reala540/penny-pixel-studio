"""Search briefs, keyword-stuffing notes, packaging that learns from real results, and boost suggestions (which
never spend money). AI and platforms are faked."""

import uuid

from studio import analytics, db, notify
from studio.script import pipeline
from studio.script.models import Package, SearchBrief

from .test_end_to_end import silent_tts  # noqa: F401  (fixture)
from .test_performance import _published_youtube_post
from .test_produce_idea import setup_ideas
from studio import produce


def _pkg(**over):
    base = dict(youtube_title="Budgeting basics", youtube_description="Budgeting basics explained.", tags=["budgeting basics"],
                thumbnail_headlines=["a", "b", "c"], x_post="x", facebook_post="f", shorts=[],
                search_brief=SearchBrief(audience="first-job earners", question="how do I make a budget",
                                         primary_phrase="budgeting basics", supporting_phrases=["50/30/20 rule"]))
    return Package(**{**base, **over})


def test_keyword_stuffing_is_flagged_never_rewritten():
    assert pipeline.search_problems(_pkg()) == []
    stuffed = _pkg(youtube_description="budgeting basics " * 5)
    assert "keyword stuffing" in pipeline.search_problems(stuffed)[0]
    assert "budgeting basics " * 5 == stuffed.youtube_description       # the text itself isn't changed
    assert "Too many tags" in pipeline.search_problems(_pkg(tags=[f"budgeting basics {i}" for i in range(5)]))[0]
    assert pipeline.search_problems(_pkg(search_brief=None)) == []


def _add_youtube_posts(c, views):
    for i, v in enumerate(views):
        _, pp = _published_youtube_post(c, video_id=f"yt{i}-{uuid.uuid4().hex[:6]}", title=f"Video {i}")
        db.run(c, "insert into post_metrics (published_post_id, collected_on, views, missing, source) values (%s, current_date, %s, '{}', 'test')", (pp, v))


def test_hints_only_with_enough_real_results(synced):
    c = synced
    _add_youtube_posts(c, [50, 60, 70, 80])
    assert analytics.packaging_hints(c, "ai") == ""                       # four videos tell you nothing yet
    _add_youtube_posts(c, [900])
    h = analytics.packaging_hints(c, "ai")
    assert "Titles that did best so far" in h and "900 views" in h and "Based on 5 videos" in h
    assert analytics.packaging_hints(c, "money") == ""


def test_the_writer_sees_the_hints(synced, monkeypatch, silent_tts):
    c = synced
    router, storage, ideas = setup_ideas(c, monkeypatch, n=1, channel="ai")
    _add_youtube_posts(c, [50, 60, 70, 80, 900])
    seen = []
    real = router._chat_once

    def spy(cand, role, messages, **kw):
        if role == "repurposer":
            seen.append(messages[1]["content"])
        return real(cand, role, messages, **kw)
    monkeypatch.setattr(router, "_chat_once", spy)
    produce.produce_idea(c, router, storage, content_idea_id=ideas[0]["id"])
    assert seen and "Your own past results" in seen[0] and "search_brief" in seen[0]
    assert "never claim volumes" in seen[0]


def test_boost_suggestions_need_a_clear_winner_and_a_recent_facebook_post(synced):
    c = synced
    _add_youtube_posts(c, [50, 60, 70, 80])
    winner_pid, winner_pp = _published_youtube_post(c, video_id="star")
    db.run(c, "insert into post_metrics (published_post_id, collected_on, views, missing, source) values (%s, current_date, 1000, '{}', 'test')", (winner_pp,))
    assert analytics.boost_suggestions(c) == []                          # no Facebook post for it yet
    fb = db.one(c, "select id from social_accounts where platform='facebook'")["id"]
    v = db.one(c, "insert into content_variants (project_id, social_account_id, kind, status) values (%s,%s,'text_post','published') returning id", (winner_pid, fb))["id"]
    sp = db.one(c, "insert into scheduled_posts (variant_id, social_account_id, scheduled_at, status, idempotency_key) values (%s,%s,now(),'published',%s) returning id", (v, fb, f"post:{v}"))["id"]
    db.run(c, "insert into published_posts (scheduled_post_id, platform, url, visibility, method, social_account_id) values (%s,'facebook','https://fb.test/1','public','api',%s)", (sp, fb))
    s = analytics.boost_suggestions(c)
    assert len(s) == 1 and s[0]["views"] == 1000 and s[0]["facebook_url"] == "https://fb.test/1"
    assert analytics.notify_boosts(c) == 1 and analytics.notify_boosts(c) == 1
    assert db.one(c, "select count(*) n from notifications where kind='boost_suggestion'")["n"] == 1   # told once
    assert "boost_suggestion" in notify.ROUTINE                          # an optional update, not an alarm
    assert db.one(c, "select count(*) n from budget_reservations")["n"] == 0                            # nothing spent
