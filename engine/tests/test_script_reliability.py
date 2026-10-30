"""Script reliability: one regression test per cause found in the 28 Oct review of real packages (Penny's Cash ISA
video and four Pixel videos). All AI answers here are scripted (mocked); no provider is called.

Causes: the checker saw only the first 1,500 characters of a source and never its date; the fact sheet wasn't
saved with the script; wrong sums, fact keys used as claim links and animation labels were reported, not fixed;
the final check ran after the last repair; the critic's cuts couldn't be applied; repeated disclaimers; off-topic
and old sources; Shorts always too thin with no repair; a busy polishing model failed the whole package; and every
note looked like a blocker."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from studio.errors import TransientError
from studio.script import evidence, pipeline, quality, repair, verify
from studio.script.models import Claim, ClaimVerdicts, Fact, FactSheet, Scene, Script, ShortScript, Visual

NOW = datetime(2026, 10, 28, tzinfo=timezone.utc)


class Stub:
    """A router that answers each role from a function: (prompt, schema) -> dict."""

    def __init__(self, **answers):
        self.answers, self.prompts = answers, []

    def complete(self, role, prompt, schema=None, **kw):
        self.prompts.append((role, prompt))
        fn = self.answers.get(role)
        if fn is None:
            raise TransientError(f"no free model for {role}")
        data = schema.model_validate(fn(prompt)) if schema else fn(prompt)
        return SimpleNamespace(data=data, trail=lambda: {"companies": ["stub"]}, companies=lambda: {"stub"},
                               provider="stub", model="m", input_tokens=0, output_tokens=0)


def _source(i, title, body, published, topic="money", summary=""):
    return {"id": f"src-{i}", "adapter": "web_article", "title": title, "publisher": "Pub", "url": f"https://x/{i}",
            "published_at": published, "summary": summary, "credibility": "news", "topic": topic, "body_text": body}


GUARDIAN = _source(1, "Bank of England: UK interest rates hiked to 0.25% to combat surge in inflation",
                   ("Live updates from the markets. " * 40) + "The Bank of England raised interest rates to 0.25% from "
                   "0.1%, as inflation hit 5.1%. " + ("Traders reacted across Europe. " * 15)
                   + "The US Federal Reserve signalled it expects to raise rates three times in 2022. " + ("More. " * 50),
                   datetime(2021, 12, 16, tzinfo=timezone.utc))


def _fact(key, text, src, kind="current", passage=""):
    return Fact(key=key, text=text, source_ref="S1", passage=passage or text, time_kind=kind, source_id=src["id"],
                published=src["published_at"].date().isoformat())


def _script(claims, scenes, cta="Subscribe. This is general education, not personal advice.", facts=()):
    return Script(title="T", hook="Hook here.", promise="P", scenes=scenes, claims=claims, cta=cta, facts=list(facts))


def _scene(text, keys=(), visual=None):
    return Scene(narration=text, visual=visual or Visual(type="title_card", headline="H"), claim_keys=list(keys))


def _supported_checker(prompt):
    """Says supported and quotes the evidence line it was given, as a careful checker would."""
    import re

    out = []
    for key, block in re.findall(r'<evidence id="(C\d+)">(.*?)</evidence>', prompt, flags=re.S):
        lines = [x for x in block.splitlines() if x.strip() and not x.startswith(("Fact:", "Source:", "More from"))]
        quote = next((x.replace("Passage: ", "") for x in lines if "three times" in x or "0.25" in x or "Passage" in x), lines[0])
        out.append({"key": key, "status": "supported", "supporting_quote": quote.strip()[:200], "note": ""})
    return {"verdicts": out}


# ------------------------------------------------------------------ evidence reaches the checker

def test_the_checker_sees_the_part_of_a_long_article_that_matters():
    fact = _fact("F1", "The US Federal Reserve expects to raise rates three times in 2022", GUARDIAN, kind="historical",
                 passage="The Bank of England raised interest rates")
    text = evidence.evidence_for(fact, {GUARDIAN["id"]: GUARDIAN}, "The Fed expected to raise rates three times in 2022")
    assert GUARDIAN["body_text"].index("three times") > 1500          # the old checker never saw it
    assert "three times in 2022" in text and "published 2021-12-16" in text


def test_a_year_given_by_the_sources_date_counts():
    fact = _fact("F1", "The Bank of England raised interest rates to 0.25%", GUARDIAN, kind="historical",
                 passage="The Bank of England raised interest rates to 0.25% from 0.1%, as inflation hit 5.1%.")
    claim = Claim(key="C1", text="The Bank of England raised interest rates to 0.25% in 2021.", fact_refs=["F1"])
    script = _script([claim], [_scene("In December 2021 the Bank raised rates to 0.25%.", ["C1"])], facts=[fact])
    rec = verify.check_claims(Stub(claim_checker=_supported_checker), script, FactSheet(facts=[fact]), [GUARDIAN])
    assert rec[0]["status"] == "supported", rec[0]["note"]


def test_an_old_figure_said_as_current_is_caught_and_said_with_its_date_passes():
    fact = _fact("F1", "Inflation hit 5.1%", GUARDIAN, kind="historical", passage="as inflation hit 5.1%.")
    stale = Claim(key="C1", text="Inflation is 5.1%.", fact_refs=["F1"])
    dated = Claim(key="C2", text="In 2021 inflation hit 5.1%.", fact_refs=["F1"])
    script = _script([stale, dated], [_scene("x " * 20, ["C1", "C2"])], facts=[fact])
    rec = {r["key"]: r for r in verify.check_claims(Stub(claim_checker=_supported_checker), script, FactSheet(facts=[fact]), [GUARDIAN])}
    assert rec["C1"]["status"] == "stale" and "2021" in rec["C1"]["note"]
    assert rec["C2"]["status"] == "supported"


def test_a_forecast_must_be_said_as_a_forecast():
    fact = _fact("F1", "Inflation will rise to 6% next spring", GUARDIAN, kind="forecast",
                 passage="The US Federal Reserve signalled it expects to raise rates three times in 2022.")
    as_fact = Claim(key="C1", text="Rates rise three times in 2022.", fact_refs=["F1"])
    as_forecast = Claim(key="C2", text="The Fed expected to raise rates three times in 2022.", fact_refs=["F1"])
    script = _script([as_fact, as_forecast], [_scene("x " * 20, ["C1", "C2"])], facts=[fact])
    rec = {r["key"]: r for r in verify.check_claims(Stub(claim_checker=_supported_checker), script, FactSheet(facts=[fact]), [GUARDIAN])}
    assert rec["C1"]["status"] == "unsupported" and "forecast" in rec["C1"]["note"]
    assert rec["C2"]["status"] == "supported"


def test_ordinary_principles_are_not_failed_as_unsourced_facts():
    ok = Claim(key="C1", text="Inflation reduces what the same amount of cash can buy over time.", kind="principle")
    sneaky = Claim(key="C2", text="Inflation always cuts savings by 5% a year.", kind="principle")
    script = _script([ok, sneaky], [_scene("x " * 20, ["C1", "C2"])])
    rec = {r["key"]: r for r in verify.check_claims(Stub(), script, FactSheet(facts=[]), [])}
    assert rec["C1"]["status"] == "general"
    assert rec["C2"]["status"] == "unsupported"                       # a "principle" with a figure is a fact


def test_comparisons_are_checked_by_code():
    assert verify.check_calculation("The ISA's 1% is lower than the 6% inflation forecast", "0.01 < 0.06", set())[0] == "supported"
    assert verify.check_calculation("1% is higher than 6%", "0.01 > 0.06", set())[0] == "contradicted"


# ------------------------------------------------------------------ code repairs

def test_a_wrong_sum_is_recalculated_everywhere_it_was_said():
    calc = Claim(key="C1", kind="calculation", expression="(1 + 0.04)**10 * 1000 - 1000",
                 text="Investing £1,000 at 4% for 10 years earns about £300 more")
    jars = Visual(type="animated", animation="budget_jars", items=["Cash ISA|£100", "Tracker|£300"])
    script = _script([calc], [_scene("Over 10 years £1,000 at 4% earns about £300 more than cash.", ["C1"], jars)])
    rec = [{"key": "C1", "status": "contradicted", "note": ""}]
    fixed, changes = repair.fix_calculations(script, rec)
    assert "480" in fixed.claims[0].text and "300" not in fixed.claims[0].text
    assert "£480" in fixed.scenes[0].narration and fixed.scenes[0].visual.items[1] == "Tracker|£480"
    assert changes and verify.check_calculation(fixed.claims[0].text, calc.expression, {"1000", "0.04", "4"})[0] == "supported"


def test_a_wrong_percentage_is_recalculated_as_a_percentage():
    calc = Claim(key="C1", kind="calculation", expression="(37.5 - 10.7) / 10.7",
                 text="Capital spending rose 58% from $10.7 billion to $37.5 billion")
    script = _script([calc], [_scene("Spending rose 58% in two years, from $10.7 billion to $37.5 billion.", ["C1"])])
    fixed, _ = repair.fix_calculations(script, [{"key": "C1", "status": "contradicted", "note": ""}])
    assert "250%" in fixed.claims[0].text and "250%" in fixed.scenes[0].narration


def test_fact_keys_used_as_claim_links_are_corrected():
    c = Claim(key="C4", text="t", fact_refs=["F11"])
    script = _script([c], [_scene("x " * 20, ["F11", "C99"])])
    fixed, changes = repair.fix_claim_links(script)
    assert fixed.scenes[0].claim_keys == ["C4"] and changes
    assert not [i for i in quality.check_long(fixed, "ai", min_seconds=0) if "unknown claims" in i]


def test_animation_labels_must_be_said_and_a_label_that_is_said_is_kept():
    said = _scene("After a year your £1,000 becomes £1,010 in the ISA.", visual=Visual(
        type="animated", animation="budget_jars", items=["Start|£1,000", "After a year|£1,010"]))
    unsaid = _scene("After ten years the gap is large.", visual=Visual(
        type="animated", animation="counter", stat_value="30%", stat_label="Gap"))
    out, changes = repair.fix_animations([said, unsaid])
    assert out[0].visual.items == said.visual.items                   # "1,010" is said: not a false alarm
    assert out[1].visual.type == "title_card" and len(changes) == 1
    assert quality.animation_numbers(out) == []


def test_repeated_sentences_and_disclaimers_are_removed_not_padded():
    d = "This is general education, not personal advice."
    scenes = [_scene(f"Opening idea about savings and interest rates today. {d}"),
              _scene(f"The cash ISA pays one percent while prices rise faster than that every year. {d}"),
              _scene("The cash ISA pays one percent while prices rise faster than that every year. And a new point "
                     "about what that means for a five year plan, with a worked example coming next.")]
    script = _script([], scenes)
    fixed, changes = repair.remove_repeats(script, money=True)
    text = fixed.full_text()
    assert d not in text and d in fixed.cta                           # said once, at the end
    assert text.count("The cash ISA pays one percent") == 1
    assert not quality.repeated_sentences(fixed.full_text() + " " + fixed.cta)
    assert any("disclaimer" in c for c in changes)
    # the required disclaimer twice is not itself "padding"
    assert quality.repeated_sentences(f"{d} {d}") == []


def test_the_critics_cuts_and_merges_are_applied_but_never_the_opening_or_ending():
    scenes = [_scene(f"Scene {i} " + "words " * 20, [f"C{i}"]) for i in range(1, 7)]
    out, merged_at, notes = repair.apply_edit_plan(scenes, delete=[1, 4, 6], merge=[[2, 3]])
    assert [s.narration.split()[1] for s in out] == ["1", "2", "5", "6"]   # 4 removed; 1 and 6 protected
    assert out[1].claim_keys == ["C2", "C3"] and merged_at == [2]


def test_an_unsupportable_scene_is_removed_only_if_the_video_stays_long_enough():
    scenes = [_scene("words " * 60, [f"C{i}"]) for i in range(1, 6)]
    claims = [Claim(key=f"C{i}", text="t", fact_refs=["F1"]) for i in range(1, 6)]
    script = _script(claims, scenes)
    rec = [{"key": "C3", "status": "unsupported", "note": ""}]
    out, notes, left = repair.drop_unsupported_scenes(script, rec, min_seconds=60)
    assert len(out.scenes) == 4 and not left and "C3" not in {c.key for c in out.claims}
    kept, _, left = repair.drop_unsupported_scenes(script, rec, min_seconds=10_000)
    assert len(kept.scenes) == 5 and [r["key"] for r in left] == ["C3"]


# ------------------------------------------------------------------ evidence before writing

def test_off_topic_sources_are_set_aside():
    isa = _source(2, "Cash ISA rates vs inflation: are savers losing?", "Cash ISA savers face inflation...", NOW)
    api = _source(3, "Show HN: Exchangr – Real-Time and Historical Forex Rates API", "161 currencies via REST", NOW)
    kept, notes = evidence.relevant_sources({"title": "Cash ISA or invest? The cost of playing it safe",
                                             "angle": "savings vs inflation"}, [isa, api])
    assert kept == [isa] and "Exchangr" in notes[0]


def test_facts_keep_their_passage_and_date_and_old_ones_become_history():
    sheet = FactSheet(facts=[Fact(key="F1", text="Inflation hit 5.1%", source_ref="S1"),
                             Fact(key="F2", text="Unicorns pay 9% interest", source_ref="S1")])
    out, dropped = evidence.attach(sheet, [GUARDIAN], now=NOW)
    assert [f.key for f in out.facts] == ["F1"] and "F2" in dropped[0]
    f = out.facts[0]
    assert "5.1%" in f.passage and f.published == "2021-12-16" and f.source_id == "src-1"
    assert f.time_kind == "historical"                                # a 2021 figure in a 2026 video


def test_the_video_is_as_long_as_the_evidence_supports():
    assert pipeline.planned_minutes(10) == 6.0
    assert pipeline.planned_minutes(30) == 11.0
    assert pipeline.planned_minutes(3) == 5.0


# ------------------------------------------------------------------ status: four kinds, never mixed

def test_findings_separate_blockers_warnings_missing_parts_and_notes():
    script = _script([], [_scene("word " * 100)])
    claims = [{"key": "C1", "text": "Rates fell 9%", "status": "unsupported", "note": "no source"}]
    critic = pipeline.CriticReport(hook=6, originality=8, clarity=8, pacing=8, value=8, fixes=["Scene 1: sharper"])
    out = pipeline.classify(["Sentences too long on average (24.0 words)", "Scene 2 states numbers ['9'] without a claim/source"],
                            claims, critic, script, 1.0, ["Recalculated C3"])
    kinds = {(f["kind"], f["code"]) for f in out}
    assert ("blocker", "claim_unsupported") in kinds and ("warning", "critic_low") in kinds
    assert ("info", "repair") in kinds and ("info", "shorter_video") in kinds
    by_text = {f["text"]: f["kind"] for f in out}
    assert by_text["Sentences too long on average (24.0 words)"] == "warning"
    assert by_text["Scene 2 states numbers ['9'] without a claim/source"] == "blocker"
    pkg = pipeline.package_findings(["Title marked as UK-specific", "Short 'A' dropped: ['Short too thin: ~4s']",
                                     "X post states numbers not in the evidence: ['42']"])
    assert [f["kind"] for f in pkg] == ["info", "missing", "blocker"]


# ------------------------------------------------------------------ Shorts and posts

def _short(words, title="S"):
    per = max(words // 4, 1)
    return {"title": title, "hook": "Here is the quick version.", "caption": "c", "hashtags": ["money"],
            "scenes": [{"narration": " ".join(["save"] * per) + ".", "visual": {"type": "title_card", "headline": "h"},
                        "claim_keys": []} for _ in range(4)]}


def test_a_thin_short_is_repaired_on_its_own():
    import re

    lines = ["Put a little away each week.", "Watch what it does by spring.", "Small amounts grow into real savings.",
             "Check the rate before you lock it in.", "Compare two options side by side.", "Pick the one you can keep.",
             "Write the plan on one page.", "Review it once a month.", "Cut one cost you never use.",
             "Move that money first.", "Keep an emergency pot apart.", "Leave the rest to grow quietly.",
             "Ask what happens if prices rise.", "Note the answer somewhere safe.", "Repeat it next year.",
             "That is the whole routine."]

    def lengthen(prompt):
        return {**_short(0, "Fixed"), "scenes": [{"narration": " ".join(lines[i * 4:i * 4 + 4]),
                                                   "visual": {"type": "title_card", "headline": "h"},
                                                   "claim_keys": []} for i in range(4)]}
    thin = ShortScript.model_validate(_short(12))
    stub = Stub(repurposer=lengthen)
    fixed = pipeline.repair_short(stub, "ai", thin, ["Short too thin: ~4s"], FactSheet(facts=[]))
    assert fixed is not None and not quality.check_short(fixed, "ai")
    assert all(r == "repurposer" for r, _ in stub.prompts) and "90-130 spoken words" in stub.prompts[0][1]


def test_post_texts_may_only_state_numbers_from_the_evidence():
    fact = _fact("F1", "Inflation hit 5.1%", GUARDIAN, kind="historical")
    pkg = pipeline.Package.model_construct(x_post="Inflation hit 5.1% in 2021", facebook_post="Rates will hit 9%",
                                           youtube_title="Cash ISA vs investing")
    problems = pipeline.post_number_problems(pkg, FactSheet(facts=[fact]))
    assert problems == ["Facebook post states numbers not in the evidence: ['9']"]


# ------------------------------------------------------------------ the whole flow, with a busy polishing model

def _flow_router(bad_first=True):
    """Draft-free repair flow: the voice editor is busy, the critic asks for a cut, the checker supports what the
    evidence says, and the rewrite qualifies the unsupported claim."""
    state = {"rewrites": 0}

    def critic(prompt):
        return {"hook": 8, "originality": 8, "clarity": 8, "pacing": 5, "value": 8, "fixes": ["Scene 3 repeats scene 2"],
                "weak_scenes": [], "delete": [3], "merge": []}

    def writer(prompt):
        state["rewrites"] += 1
        return {"scenes": [{"narration": "In December 2021 the Bank of England raised rates to 0.25% as inflation hit "
                            "5.1%, so cash lost value that year.", "visual": {"type": "title_card", "headline": "2021"},
                            "claim_keys": ["C2"]}],
                "claims": [{"key": "C2", "text": "In 2021 the Bank of England raised rates to 0.25%", "kind": "fact",
                            "fact_refs": ["F1"]}]}

    return Stub(claim_checker=_supported_checker, critic=critic, scriptwriter=writer,
                angle_selector=lambda p: {"best": 0, "reason": "ok"}), state


def test_repair_flow_fixes_what_it_can_and_finishes_without_the_busy_model(monkeypatch):
    monkeypatch.setattr(quality, "MIN_LONG_SECONDS", 20)
    monkeypatch.setattr("studio.config.services", lambda: {"render": {"min_long_minutes_floor": 0.3, "max_long_minutes": 14,
                                                                       "target_long_minutes": 11, "min_long_minutes": 8}})
    fact = _fact("F1", "The Bank of England raised interest rates to 0.25%", GUARDIAN, kind="historical",
                 passage="The Bank of England raised interest rates to 0.25% from 0.1%, as inflation hit 5.1%.")
    scenes = [_scene("Saving feels safe, yet the price of safety is easy to miss until you look at a whole year."),
              _scene("The Bank raised rates to 0.25%. That sounds like a lot until you compare it with prices.", ["C2"]),
              _scene("Saving feels safe, yet the price of safety hides in plain sight for most people we know."),
              _scene("A second idea matters here: what you can do with money you will not touch for five years."),
              _scene("A practical step is to split long-term savings from the emergency pot you may need soon."),
              _scene("One more check: what the fees take each year, because a small fee compounds like interest."),
              _scene("To wrap up, check the real rate after prices, not the headline rate printed on the account.")]
    claims = [Claim(key="C2", text="The Bank of England raised rates to 0.25%", fact_refs=["F1"])]
    script = _script(claims, scenes, facts=[fact])
    router, state = _flow_router()
    trail: list = []
    result = pipeline.finish_long(router, "ai", script, FactSheet(facts=[fact]), [GUARDIAN], set(), trail)
    steps = [t["step"] for t in trail]
    assert "voice_edit" in steps and trail[steps.index("voice_edit")].get("skipped")   # busy: skipped, not failed
    assert len(result.script.scenes) == 6                                  # the critic's cut was applied
    assert state["rewrites"] == 0                                          # dated by code: no rewrite needed
    assert "(as of December 2021)" in result.script.full_text()
    statuses = {c["key"]: c["status"] for c in result.claims}
    assert statuses == {"C2": "supported"} and not result.issues
    assert result.script.facts and result.report["findings"]
    assert {f["kind"] for f in result.report["findings"]} <= {"info", "warning"}


def test_unsupported_content_still_fails(monkeypatch):
    monkeypatch.setattr(quality, "MIN_LONG_SECONDS", 20)
    fact = _fact("F1", "The Bank of England raised interest rates to 0.25%", GUARDIAN, kind="historical")
    scenes = [_scene("Opening words " * 6)] + [_scene("Unicorns pay 9% interest on savings, honestly and truly. " * 2, ["C1"])
                                              for _ in range(4)] + [_scene("Wrap words " * 6)]
    claims = [Claim(key="C1", text="Unicorns pay 9% interest", fact_refs=["F1"])]
    script = _script(claims, scenes, facts=[fact])

    def checker(prompt):
        return {"verdicts": [{"key": "C1", "status": "unsupported", "supporting_quote": "", "note": "not in source"}]}

    def writer(prompt):  # the rewrite keeps the same unsupported statement
        import re
        n = len(re.search(r"scene numbers \[([^\]]*)\]", prompt).group(1).split(","))
        return {"scenes": [{"narration": "Unicorns pay 9% interest on savings, honestly and truly. " * 2,
                            "visual": {"type": "title_card", "headline": "x"}, "claim_keys": ["C1"]} for _ in range(n)],
                "claims": [{"key": "C1", "text": "Unicorns pay 9% interest", "fact_refs": ["F1"]}]}

    router = Stub(claim_checker=checker, scriptwriter=writer, critic=lambda p: {"hook": 8, "originality": 8, "clarity": 8,
                  "pacing": 8, "value": 8}, angle_selector=lambda p: {"best": 0, "reason": "ok"})
    result = pipeline.finish_long(router, "ai", script, FactSheet(facts=[fact]), [GUARDIAN], set(), [])
    assert result.needs_attention and any("Not backed" in i for i in result.issues)
    repairs = [t for t in router.prompts if t[0] == "scriptwriter"]
    assert 1 <= len(repairs) <= pipeline.REPAIR_ROUNDS                      # bounded


# ------------------------------------------------------------------ repairing existing packages (database)

from studio import db, produce  # noqa: E402

from .fakes import ScriptedRouter  # noqa: E402
from .test_end_to_end import _approve_all, produced, silent_tts  # noqa: E402,F401


MORE = ("delta", "epsilon")  # independent companies that wrote nothing of these packages


def _long(conn, channel):
    return db.one(conn, "select * from content_projects where format='long' and channel_slug=%s", (channel,))


def _counts(conn):
    return {t: db.one(conn, f"select count(*) n from {t}")["n"]
            for t in ("content_projects", "scheduled_posts", "content_variants", "publish_attempts")}


def test_repair_saves_a_new_version_keeps_the_old_and_duplicates_nothing(produced, monkeypatch):
    conn, storage = produced
    for channel in ("money", "ai"):   # Penny and Pixel
        p = _long(conn, channel)
        db.run(conn, "update content_projects set status='needs_attention' where id=%s", (p["id"],))
        before = _counts(conn)
        old = db.one(conn, "select id, version from script_versions where id=%s", (p["current_script_version_id"],))
        out = produce.repair_package(conn, ScriptedRouter(monkeypatch, extra=MORE), storage, p["id"])
        assert out.get("script_version_id"), out
        after = _counts(conn)
        assert after == before, (before, after)          # no new project, post, variant or publishing attempt
        now = db.one(conn, "select current_script_version_id, status, quality_report from content_projects where id=%s", (p["id"],))
        new = db.one(conn, "select version, origin, body from script_versions where id=%s", (now["current_script_version_id"],))
        assert new["origin"] == "repair" and new["version"] == old["version"] + 1
        assert db.one(conn, "select 1 from script_versions where id=%s", (old["id"],))          # the original is kept
        assert new["body"]["facts"] and all(f["passage"] and f["source_id"] for f in new["body"]["facts"])
        assert now["status"] == "ready_for_review", now["quality_report"].get("findings")
        assert now["quality_report"]["repaired_from_version"] == old["version"] and out["status"] == "ready_for_review"
        claims = db.all_(conn, "select status, source_id from research_claims where script_version_id=%s",
                         (now["current_script_version_id"],))
        assert claims and all(c["status"] in ("supported", "partially_supported", "general", "opinion") for c in claims)
        # running it again for the same version does nothing new
        db.run(conn, "update content_projects set status='needs_attention' where id=%s", (p["id"],))
        versions = db.one(conn, "select count(*) n from script_versions where project_id=%s", (p["id"],))["n"]
        produce.repair_package(conn, ScriptedRouter(monkeypatch, extra=MORE), storage, p["id"])
        assert db.one(conn, "select count(*) n from script_versions where project_id=%s", (p["id"],))["n"] == versions + 1


def test_repair_without_an_independent_checker_waits_and_changes_nothing(produced, monkeypatch):
    conn, storage = produced
    p = _long(conn, "money")
    db.run(conn, "update content_projects set status='needs_attention' where id=%s", (p["id"],))
    version = p["current_script_version_id"]
    out = produce.repair_package(conn, ScriptedRouter(monkeypatch), storage, p["id"])  # only the writers' companies
    assert "No independent AI" in out["error"]
    now = db.one(conn, "select current_script_version_id, status from content_projects where id=%s", (p["id"],))
    assert now["current_script_version_id"] == version and now["status"] == "needs_attention"


def test_repair_refuses_approved_and_posted_packages(produced, monkeypatch):
    conn, storage = produced
    p = _long(conn, "money")
    _approve_all(conn)
    with pytest.raises(ValueError, match="only unapproved"):
        produce.repair_package(conn, ScriptedRouter(monkeypatch, extra=MORE), storage, p["id"])
    db.run(conn, "update content_projects set status='needs_attention' where id=%s", (p["id"],))
    sp = db.one(conn, """select sp.id from scheduled_posts sp join content_variants v on v.id=sp.variant_id
                         where v.project_id=%s limit 1""", (p["id"],))
    db.run(conn, "update scheduled_posts set status='publishing' where id=%s", (sp["id"],))
    with pytest.raises(ValueError, match="already posted"):
        produce.repair_package(conn, ScriptedRouter(monkeypatch, extra=MORE), storage, p["id"])


def test_too_little_evidence_stops_with_a_clear_next_step(produced, monkeypatch):
    conn, storage = produced
    p = _long(conn, "ai")
    db.run(conn, "update content_projects set status='needs_attention' where id=%s", (p["id"],))
    monkeypatch.setattr(pipeline, "MIN_LONG_FACTS", 50)
    from studio.errors import NeedsReview

    with pytest.raises(NeedsReview, match="Not enough evidence.*narrow the topic"):
        produce.repair_package(conn, ScriptedRouter(monkeypatch, extra=MORE), storage, p["id"])
    assert db.one(conn, "select status from content_projects where id=%s", (p["id"],))["status"] == "needs_attention"


def test_a_general_principle_is_stored_as_general(synced):
    from studio.produce import _claim_status

    assert _claim_status(synced, {"status": "general", "note": "General principle"}) == ("general", "General principle")


def test_warnings_alone_leave_a_package_reviewable_and_blockers_do_not(produced):
    conn, _ = produced
    p = _long(conn, "ai")
    for kinds, expected in ((["warning", "info", "missing"], "ready_for_review"), (["blocker"], "needs_attention")):
        qr = {**(p["quality_report"] or {}), "findings": [{"kind": k, "code": "x", "text": k} for k in kinds],
              "issues": ["something"]}
        db.run(conn, "update content_projects set status='rendering', quality_report=%s where id=%s", (db.j(qr), p["id"]))
        produce.final_status(conn, p["id"])
        assert db.one(conn, "select status from content_projects where id=%s", (p["id"],))["status"] == expected


# ------------------------------------------------------------------ found replaying the live packages' real sums

@pytest.mark.parametrize("text, expression, facts, expected", [
    ("The company earned $2.72 in benefits for every dollar invested in AI.", "2.72 = 272 / 100", {"272"}, "supported"),
    ("$470,000 for every $1 million invested, assuming a 53% success rate", "1000000 * (1 - 0.53)", {"53"}, "supported"),
    ("If it takes six months, that's six months of lost revenue.", "6", {"6"}, "unsupported"),       # not a sum
    ("The chart shows the potential time savings.", "10 + 20", {"10", "20"}, "unsupported"),           # no result said
    ("Returns from $530,000 worth of models", "1000000 * 0.53", {"53"}, "unsupported"),               # unstated input
    ("The AI spend per employee is $187,500.", "37500000000 / 200000", {"37.5"}, "unsupported"),     # invented headcount
])
def test_real_sums_are_judged_on_what_they_say(text, expression, facts, expected):
    assert verify.check_calculation(text, expression, facts)[0] == expected


def test_a_year_is_never_taken_for_a_sums_result():
    calc = Claim(key="C15", kind="calculation", expression="(37.5 - 10.7) / 10.7",
                 text="Microsoft's capital expenditures increased by 58% from the fourth quarter of its fiscal 2023 to "
                      "the second quarter of its fiscal 2026.")
    script = _script([calc], [_scene(calc.text, ["C15"])])
    fixed, _ = repair.fix_calculations(script, [{"key": "C15", "status": "contradicted", "note": ""}])
    assert "250%" in fixed.claims[0].text and "fiscal 2023" in fixed.claims[0].text


def test_each_fact_points_at_its_own_sentence():
    eu = Fact(key="F11", text="The European Central Bank scaled back its multi-trillion euro quantitative easing package",
              source_ref="S1")
    text = ("Samuel Tombs, the chief UK economist at Pantheon, said the MPC is worried about inflation. The pound rose "
            "sharply on Thursday. In a sign of institutions scrambling to tackle inflationary pressures worldwide, the "
            "European Central Bank also said on Thursday it would scale back its multi-trillion euro quantitative "
            "easing pandemic support package. The US Federal Reserve said earlier this week it anticipated raising "
            "rates three times in 2022.")
    passage = evidence.find_passage(eu, text)
    assert passage.startswith("In a sign") and "Samuel" not in passage and "Federal Reserve" not in passage


# ------------------------------------------------------------------ found in the first real run (29 Oct, actual providers)

def test_numbers_in_names_are_labels_not_figures():
    s = _script([], [_scene("Picture a $200,000 mortgage on a 30-year term. GPT-6.1 Terra and Kimi K3.1 shipped in Q4.") for _ in range(6)])
    issues = quality.check_long(s, "ai", min_seconds=0)
    assert not [i for i in issues if "states numbers" in i and ("'30'" in i or "6.1" in i)]
    assert [i for i in issues if "states numbers ['200000']" in i]          # a real figure still needs its claim
    pkg = pipeline.Package.model_construct(x_post="The 30-year rate tells the story", facebook_post="GPT-6.1 is out",
                                           youtube_title="Mortgages explained")
    assert pipeline.post_number_problems(pkg, FactSheet(facts=[])) == []


def test_official_and_clearly_related_sources_are_kept():
    official = _source(4, "30-year mortgage rate — latest official data", "", NOW)
    official["credibility"] = "primary_data"
    fomc = _source(5, "Federal Reserve issues FOMC statement", "The Committee decided to lower the target range", NOW)
    fomc["credibility"] = "official"
    blog = _source(6, "Mortgage payments rise as rates climb", "Homeowners see payments rising", NOW)
    unrelated = _source(7, "Show HN: a forex API", "161 currencies", NOW)
    kept, notes = evidence.relevant_sources({"title": "Mortgage Rates Hit 7.32% While the Fed Cuts — Why Your Payment "
                                             "Keeps Rising", "angle": "the gap between the policy rate and mortgage rates"},
                                            [official, fomc, blog, unrelated])
    assert kept == [official, fomc, blog] and len(notes) == 1


def test_a_number_that_cannot_be_the_result_is_never_replaced():
    calc = Claim(key="C15", kind="calculation", expression="(200000*0.05*30) - (200000*0.04*30)",
                 text="A 1% higher rate on a $200,000 loan costs much more over the term")
    script = _script([calc], [_scene("A 1% higher rate on a $200,000 loan costs much more over the term.", ["C15"])])
    fixed, changes = repair.fix_calculations(script, [{"key": "C15", "status": "contradicted", "note": ""}])
    assert fixed.claims[0].text == calc.text and not changes            # "1%" isn't a typo of 60,000


def test_spoken_arithmetic_is_removed_from_the_narration():
    c = Claim(key="C1", kind="calculation", expression="124*12*30", text="That adds up to $44,640, calculated as 124*12*30")
    script = _script([c], [_scene("That adds up to an extra $44,640 in interest, calculated as 124*12*30.", ["C1"])])
    fixed, changes = repair.remove_spoken_working(script)
    assert fixed.scenes[0].narration == "That adds up to an extra $44,640 in interest." and changes
    assert "calculated as" not in fixed.claims[0].text


def test_shorts_are_built_from_the_checked_script_when_written_ones_fail():
    lines = ["Mortgage rates climbed while the Fed cut.", "That gap surprises many buyers.", "Banks price loans off long bonds.",
             "Long bonds did not fall with the policy rate.", "So monthly payments kept rising.", "Lenders also add a margin.",
             "That margin widened this year.", "Buyers feel it in every payment.", "Shopping around still helps.",
             "Compare three offers before you sign.", "Ask each lender for the full cost.", "Check the fees, not just the rate.",
             "A small difference adds up over time.", "Write the numbers side by side.", "Then pick the offer you understand.",
             "Do not rush the decision.", "Your future self will thank you.", "That is the whole idea in one minute."]
    scenes = [_scene("Opening line for the main video, welcome to the show today.")] + \
             [_scene(" ".join(lines[i:i + 3])) for i in range(0, 18, 3)] + [_scene("Thanks for watching, see you next week.")]
    script = _script([], scenes)
    built = pipeline.shorts_from_script(script, "money", FactSheet(facts=[]), n=2)
    assert built and all(not quality.check_short(s, "money") for s in built)
    words = sum(len(sc.narration.split()) for sc in built[0].scenes) + len(built[0].hook.split())
    assert 90 <= words <= 130


def test_the_critics_cuts_are_applied_as_far_as_the_length_allows(monkeypatch):
    monkeypatch.setattr(quality, "MIN_LONG_SECONDS", 20)
    monkeypatch.setattr("studio.config.services", lambda: {"render": {"min_long_minutes_floor": 0.6, "max_long_minutes": 14,
                                                                       "target_long_minutes": 11, "min_long_minutes": 8}})
    texts = [f"Scene {i} explains one distinct thing about saving money with a careful worked example here." for i in range(1, 10)]
    script = _script([], [_scene(t) for t in texts])

    def critic(prompt):
        return {"hook": 8, "originality": 8, "clarity": 8, "pacing": 4, "value": 8, "fixes": ["cut repeats"],
                "weak_scenes": [], "delete": [2, 3, 4, 5, 6, 7], "merge": []}

    router = Stub(critic=critic, angle_selector=lambda p: {"best": 0, "reason": "ok"},
                  scriptwriter=lambda p: {"scenes": [], "claims": []})
    result = pipeline.finish_long(router, "ai", script, FactSheet(facts=[]), [], set(), [])
    assert 6 <= len(result.script.scenes) < 9                          # some cuts applied, never below 6 scenes
    assert any("of the critic's 6 suggested cuts" in c for c in result.report["repairs"])


def test_a_videos_own_sources_are_never_set_aside():
    sol = _source(8, "GPT-6.1 Sol helps CodeRabbit strengthen security across complex codebases", "CodeRabbit uses GPT-6.1 Sol", NOW, topic="ai")
    grep = _source(9, "Greptile takes bug detection beyond code review with GPT-6 Astra", "Greptile finds bugs", NOW, topic="ai")
    kept, notes = evidence.relevant_sources({"title": "Security-First Coding: GPT-6.1 Sol vs Greptile Bug Detector",
                                             "angle": "which catches more real vulnerabilities"}, [sol, grep])
    assert kept == [sol, grep] and notes == []


def test_a_recent_fact_is_not_history_unless_it_names_an_earlier_date():
    recent = _source(10, "CVE-Bench: benchmarking agents on real vulnerabilities", "CVE-Bench runs twenty real-world vulnerabilities.",
                     NOW - timedelta(days=146), topic="ai")
    sheet = FactSheet(facts=[Fact(key="F1", text="CVE-Bench runs twenty real-world vulnerabilities", source_ref="S1", time_kind="historical"),
                             Fact(key="F2", text="CVE-Bench runs twenty real-world vulnerabilities in 2025", source_ref="S1",
                                  time_kind="historical", passage="CVE-Bench runs twenty real-world vulnerabilities.")])
    out, _ = evidence.attach(sheet, [recent], now=NOW)
    assert [f.time_kind for f in out.facts] == ["current", "historical"]


def test_an_old_figure_gets_its_date_from_its_source():
    old = _source(11, "DeepSource false positives", "DeepSource aims to keep false positives under 5%.", datetime(2020, 6, 15, tzinfo=timezone.utc))
    fact = _fact("F1", "DeepSource aims to keep false positives under 5%", old, kind="historical")
    claim = Claim(key="C1", text="DeepSource aims to keep false positives under 5%.", fact_refs=["F1"])
    script = _script([claim], [_scene("Static analysis has a trust problem. DeepSource aims to keep false positives under 5%.", ["C1"])],
                     facts=[fact])
    fixed, changes = repair.qualify_stale(script, [{"key": "C1", "status": "stale", "note": ""}])
    assert "DeepSource aims to keep false positives under 5% (as of June 2020)." in fixed.scenes[0].narration
    assert fixed.scenes[0].narration.startswith("Static analysis has a trust problem.") and changes
    rec = verify.check_claims(Stub(claim_checker=_supported_checker), fixed, FactSheet(facts=[fact]), [old])
    assert rec[0]["status"] != "stale"


def test_repair_finds_saved_facts_by_source_id_not_by_label():
    """Found when the owner pressed Recheck and repair on the two real-run packages: the facts were labelled S1, S2…
    against the sources kept at writing time, and the repair matched those labels against all of the idea's sources,
    so every fact pointed at the wrong article and was set aside ('0 checkable facts')."""
    off = _source(20, "Show HN: a forex API", "161 currencies", NOW)
    fact = _fact("F1", "Inflation hit 5.1%", GUARDIAN, kind="historical", passage="as inflation hit 5.1%.")
    fact = fact.model_copy(update={"source_ref": "S1"})          # S1 = the Guardian in the writer's filtered list
    out, dropped = evidence.attach(FactSheet(facts=[fact]), [off, GUARDIAN], now=NOW)   # S1 = the forex page here
    assert [f.key for f in out.facts] == ["F1"] and out.facts[0].source_id == GUARDIAN["id"] and not dropped



# ------------------------------------------------------------------ found by the owner's Recheck and repair (29 Oct, actual providers)

def test_this_years_date_is_not_an_earlier_date():
    assert not evidence.names_past_date("CVE-Bench, June 2026", NOW)
    assert evidence.names_past_date("DeepSource in 2020", NOW) and evidence.names_past_date("three years ago", NOW)


def test_cuts_are_undone_when_the_rewrite_makes_the_video_too_short(monkeypatch):
    monkeypatch.setattr(quality, "MIN_LONG_SECONDS", 20)
    monkeypatch.setattr("studio.config.services", lambda: {"render": {"min_long_minutes_floor": 0.5, "max_long_minutes": 14,
                                                                       "target_long_minutes": 11, "min_long_minutes": 8}})
    names = ["one", "two", "three", "four", "five", "six", "seven", "eight"]
    texts = [f"Part {n} explains one distinct thing about saving money with a careful worked example here." for n in names]
    script = _script([], [_scene(t) for t in texts])

    def critic(prompt):
        return {"hook": 8, "originality": 8, "clarity": 8, "pacing": 4, "value": 8, "fixes": ["merge"],
                "weak_scenes": [], "delete": [], "merge": [[2, 3], [4, 5]]}

    def shrinking_writer(prompt):  # the rewrite of merged scenes comes back much shorter
        import re
        n = len(re.search(r"scene numbers \[([^\]]*)\]", prompt).group(1).split(","))
        return {"scenes": [{"narration": "Short.", "visual": {"type": "title_card", "headline": "x"}, "claim_keys": []}
                           for _ in range(n)], "claims": []}

    router = Stub(critic=critic, scriptwriter=shrinking_writer, angle_selector=lambda p: {"best": 0, "reason": "ok"})
    result = pipeline.finish_long(router, "ai", script, FactSheet(facts=[]), [], set(), [])
    assert len(result.script.scenes) == 8 and not any(i.startswith("Too short") for i in result.issues)
    assert any("Undid the critic's cuts" in c for c in result.report["repairs"])


def test_repair_judges_post_texts_and_shorts_again(produced, monkeypatch):
    conn, storage = produced
    p = _long(conn, "money")
    qr = {**(p["quality_report"] or {}), "findings": [
        {"kind": "blocker", "code": "package_part", "text": "Facebook post states numbers not in the evidence: ['30']"},
        {"kind": "missing", "code": "package_part", "text": "No Shorts: they couldn't be made to pass the checks"},
        {"kind": "info", "code": "package_part", "text": "Title marked as UK-specific"}]}
    db.run(conn, """update content_projects set status='needs_attention', quality_report=%s,
                    recipe = jsonb_set(recipe, '{package,facebook_post}', '"Why the 30-year rate keeps rising"') where id=%s""",
           (db.j(qr), p["id"]))
    produce.repair_package(conn, ScriptedRouter(monkeypatch, extra=MORE), storage, p["id"])
    now = db.one(conn, "select status, quality_report from content_projects where id=%s", (p["id"],))
    texts = [f["text"] for f in now["quality_report"]["findings"]]
    assert "Title marked as UK-specific" in texts                                   # notes kept
    assert not any("states numbers not in the evidence" in t for t in texts)        # '30-year' is a label
    assert not any(t.startswith("No Shorts") for t in texts)                         # it has Shorts
    assert now["status"] == "ready_for_review"


def test_a_voice_edit_may_not_shorten_the_video():
    """Found on 29 Oct: repairs shrank the mortgage video from 4.5 to 3.1 minutes; the voice edit was cutting text."""
    long = "Here is a careful and complete explanation of why the monthly payment keeps rising for ordinary buyers today."
    script = _script([], [_scene(long) for _ in range(6)])

    def editor(prompt):
        import json, re
        scenes = json.loads(prompt.split("Scenes:\n", 1)[1].split("\n\nReturn JSON", 1)[0])
        return {"hook": "Hook here.", "scenes": [{"n": s["n"], "narration": "Payments rise." if s["n"] % 2 else
                                                 s["narration"].replace("Here is", "Here's")} for s in scenes]}

    edited, _ = pipeline.voice_edit(Stub(voice_editor=editor), "ai", script, set())
    assert all(len(s.narration.split()) >= 17 for s in edited.scenes)      # the cut-down edits were refused
    assert edited.scenes[1].narration.startswith("Here's")                 # a real polish was kept
