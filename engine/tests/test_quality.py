from datetime import date, datetime, timezone

from studio import schedule
from studio.research.engine import pick, score_idea
from studio.script import quality, verify
from studio.script.models import Fact, FactSheet


def test_numbers_normalised():
    assert quality.numbers_in("It rose 4.50% to 1,200 people in 2026") == {"4.5", "1200", "2026"}


def test_banned_phrases_found_and_cleaned():
    text = "Let's dive in. This is a game-changer."
    assert set(quality.banned_hits(text)) >= {"let's dive in", "game-changer"}
    assert not quality.banned_hits(quality.remove_banned(text))


def test_money_requires_disclaimer_and_no_promises():
    issues = quality._common("This fund has guaranteed returns.", "money")
    assert any("Promises returns" in i for i in issues)
    assert any("general education" in i for i in issues)
    assert not any("general education" in i for i in quality._common("General education, not personal advice.", "money"))


def test_quote_must_really_be_in_evidence():
    ev = "The household savings rate was 4.5 percent in September 2026 according to official data"
    assert verify.quote_in_evidence("savings rate was 4.5 percent in September 2026", ev)
    assert not verify.quote_in_evidence("savings rate doubled to 9 percent last year", ev)


def test_fact_sheet_drops_numbers_not_in_source():
    sources = [{"title": "Savings", "summary": "The rate was 4.5 percent in 2026.", "body_text": None}]
    sheet = FactSheet(facts=[Fact(key="F1", text="The rate was 4.5 percent in 2026", source_ref="S1"),
                             Fact(key="F2", text="The rate will hit 12 percent", source_ref="S1"),
                             Fact(key="F3", text="Something", source_ref="S9")])
    kept, dropped = verify.ground_facts(sheet, sources)
    assert [f.key for f in kept.facts] == ["F1"]
    assert len(dropped) == 2


def test_slots_convert_nairobi_to_utc():
    s = schedule.slots(["mon"], ["18:00"], date(2026, 10, 26), "Africa/Nairobi")
    assert s == [datetime(2026, 10, 26, 15, 0, tzinfo=timezone.utc)]


def test_balance_by_mix_alternates_topics():
    items = [{"id": i, "topic": "ai"} for i in range(4)] + [{"id": 10 + i, "topic": "money"} for i in range(4)]
    picked = schedule.balance_by_mix(items, {"ai": 0.5, "money": 0.5}, 4)
    assert sorted(p["topic"] for p in picked) == ["ai", "ai", "money", "money"]


def _idea(title, cred="official", days=1, evergreen=False):
    from datetime import timedelta

    return {"title": title, "angle": "we compare the numbers step by step", "evergreen": evergreen,
            "sources": [{"credibility": cred, "published_at": datetime.now(timezone.utc) - timedelta(days=days),
                         "title": title, "adapter": "official_feeds"}]}


def test_scoring_penalises_repeats_and_rewards_evidence():
    history = ["How to build a budget that survives real life"]
    fresh = score_idea(_idea("Salary negotiation: the math of asking for more"), "money", [], history)
    repeat = score_idea(_idea("How to build a budget that survives real life"), "money", [], history)
    weak = score_idea(_idea("Salary negotiation: the math of asking for more", cred="unrated", days=25), "money", [], history)
    assert repeat["repeat"] and repeat["score"] < fresh["score"]
    assert weak["score"] < fresh["score"]
    assert "Strongest signals" in fresh["explanation"]


def test_pick_reserves_experiments():
    scored = [{"title": f"t{i}", "score": 90 - i, "repeat": False, "features": {"originality": i / 10}} for i in range(6)]
    picks = pick(scored, 3, 0.3)
    assert len(picks) == 3 and sum(1 for p in picks if p.get("is_experiment")) == 1
