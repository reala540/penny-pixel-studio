"""Affiliate offers: off until the owner adds one, disclosure first, only in long-video descriptions."""

import psycopg
import pytest

from studio import db, offers, produce

from .test_end_to_end import silent_tts  # noqa: F401  (fixture)
from .test_produce_idea import setup_ideas


def _offer(c, **over):
    row = {"name": "BudgetApp", "url": "https://budget.example/ref123", "channel_slug": "money",
           "topics": ["budget", "emergency fund"], "blurb": "A simple budgeting app", **over}
    return db.one(c, """insert into affiliate_offers (name, url, channel_slug, topics, blurb)
                        values (%(name)s, %(url)s, %(channel_slug)s, %(topics)s, %(blurb)s) returning *""", row)


def test_no_offers_means_nothing_is_added(synced):
    assert offers.add_to_description(synced, "money", "Desc", "how to budget") == ("Desc", None)


def test_matching_offer_goes_in_with_the_disclosure_first(synced):
    c = synced
    _offer(c)
    _offer(c, name="AI tool", url="https://ai.example/x", channel_slug="ai", topics=["budget"])
    text, used = offers.add_to_description(c, "money", "What we found.", "Build an emergency fund on any budget")
    assert used["name"] == "BudgetApp"
    block = text.split("\n\n", 1)[1]
    assert block.startswith("Affiliate link:") and "https://budget.example/ref123" in block
    assert block.index("Affiliate link:") < block.index("https://")            # disclosure before the link
    assert offers.MONEY_NOTE in block
    assert offers.add_to_description(c, "money", text, "budget")[1] is None    # never twice
    assert offers.add_to_description(c, "money", "D", "crypto taxes")[1] is None
    db.run(c, "update affiliate_offers set enabled=false")
    assert offers.add_to_description(c, "money", "D", "budget")[1] is None     # switched off


def test_only_https_links_and_real_topics(synced):
    c = synced
    for bad in ({"url": "http://plain.example"}, {"url": "javascript:alert(1)"}, {"topics": []}, {"channel_slug": "all"}):
        with pytest.raises(psycopg.errors.CheckViolation):
            _offer(c, **bad)


def test_a_new_package_uses_a_matching_offer_in_its_description_only(synced, monkeypatch, silent_tts):
    c = synced
    router, storage, ideas = setup_ideas(c, monkeypatch, n=1, channel="money")
    _offer(c, topics=["real numbers"])            # the fake writer's video is "The real numbers, explained"
    out = produce.produce_idea(c, router, storage, content_idea_id=ideas[0]["id"])
    pkg = db.one(c, "select recipe from content_projects where id=%s", (out["project_id"],))["recipe"]["package"]
    assert pkg.get("affiliate_offer", {}).get("name") == "BudgetApp"
    assert "Affiliate link:" in pkg["youtube_description"]
    assert "budget.example" not in pkg["x_post"] and "budget.example" not in pkg["facebook_post"]
    assert all("budget.example" not in (s.get("caption") or "") for s in pkg["shorts"])
