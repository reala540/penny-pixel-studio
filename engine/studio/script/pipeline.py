"""Adaptive multi-model script pipeline.

evidence -> draft once -> structure gate -> claim check -> voice edit -> critic ->
targeted rewrites (max 2) -> final gates. Uncertain results go to human review instead of
looping forever.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from pydantic import BaseModel

from .. import config
from ..ai.router import Router
from ..errors import NeedsReview, QuotaError, TransientError
from ..research.engine import source_block
from . import evidence, quality, repair, verify
from .models import (WORDS_PER_SECOND, CriticReport, Scene, FactSheet, Outline, OutlineSection, Package, SceneRewrite,
                     Script, SectionDraft, ShortScript)

MAX_REWRITES = 2
CRITIC_MIN = 7
MIN_LONG_FACTS = 10   # checkable facts a long video needs; fewer means padding or invention
MINUTES_PER_FACT = 0.6  # how much honest video one checked fact carries (a worked example, context, why it matters)
MIN_SCENES = 6         # the structure check's minimum: cuts never go below it
REPAIR_ROUNDS = 2       # targeted rewrites of scenes that still fail, after code has fixed what it can
FACTS_WANTED = "12-25"
SHORT_SECTION = 0.6  # a section under this share of its words gets one follow-up to finish it


@dataclass
class ScriptResult:
    script: Script
    facts: FactSheet
    claims: list[dict]
    issues: list[str]
    report: dict
    trail: list[dict] = field(default_factory=list)

    @property
    def needs_attention(self) -> bool:
        return bool(self.issues) or any(c["status"] in repair.BAD for c in self.claims)


def voice_brief(channel: str) -> str:
    ch = config.brand()["channels"][channel]
    vp = ch["voice_profile"]
    banned = ", ".join(config.brand().get("banned_phrases", []))
    aud = ch.get("audience_profile") or {}
    lines = [f"Host: {ch['host_persona'].strip()}", f"Tone: {', '.join(vp['tone'])}"]
    if aud.get("who"):
        lines.append(f"Audience: {aud['who']} ({aud.get('knowledge', 'beginner')} level), mainly in "
                     f"{', '.join(aud.get('markets') or ['US'])}. {' '.join((aud.get('writing') or '').split())}")
    lines.append("Style rules:")
    lines += [f"- {r}" for r in vp["style_rules"]]
    lines.append(f"Signature phrases (use at most one, naturally): {', '.join(vp.get('signature_phrases', []))}")
    lines.append(f"Never use these phrases: {banned}")
    if ch.get("disclaimer"):
        lines.append(f"Include this idea naturally near the start or end: {ch['disclaimer'].strip()}")
    return "\n".join(lines)


def build_fact_sheet(router: Router, idea: dict, sources: list[dict]) -> tuple[FactSheet, list[str], dict]:
    """Facts with their evidence: each keeps the passage that states it, its source's id and publication date, and
    whether it is history, current, a forecast or a general explanation. Off-topic sources are set aside first."""
    sources, off_topic = evidence.relevant_sources(idea, sources)
    # each source's full article text is shown, within a budget the free models can read in one go
    per_source = max(1500, min(6000, 30000 // max(len(sources), 1)))
    prompt = (f"Video idea: {idea['title']}\nAngle: {idea.get('angle', '')}\n\nSources:\n"
              f"{source_block(sources, body_chars=per_source)}\n\n"
              f"Extract {FACTS_WANTED} short factual statements that are directly stated in the sources, each citing its "
              "source label (S1...). Prefer specific, useful facts: numbers, dates, names, how something works, "
              "what changed and who it affects. Keep numbers exactly as written and note the period the data covers. "
              "For each, copy into passage the exact sentence(s) of the source that state it, and set time_kind: "
              "historical (a past event or a figure from an earlier period), current, forecast (a prediction or "
              "expectation: say whose) or general (a definition or how something works). Use each source's "
              "published date to judge this. Do not add anything the sources do not say.")
    res = router.complete("research_summarizer", prompt, schema=FactSheet, temperature=0.1, max_tokens=5000)
    grounded, dropped = verify.ground_facts(res.data, sources)
    linked, unlinked = evidence.attach(grounded, sources)
    return linked, off_topic + dropped + unlinked, res.trail()


def planned_minutes(n_facts: int) -> float:
    """How long the evidence lets the video be: about MINUTES_PER_FACT a checked fact, between the floor and the
    usual target. A thin topic makes a shorter honest video, never a padded one."""
    mins = long_minutes()
    floor = quality.shortest_long_seconds() / 60
    return round(min(float(mins["target"]), max(floor, n_facts * MINUTES_PER_FACT)), 1)


def _facts_block(facts: FactSheet) -> str:
    """The facts the writer may use, each with its time kind and date, so history is said as history."""
    def tag(f):
        when = f.data_period or f.published
        return (f"{f.source_ref}{', ' + f.data_period if f.data_period else ''}"
                + (f", {f.time_kind}" if f.time_kind != "current" else "")
                + (f" from {f.published}" if f.time_kind == "historical" and f.published and when == f.published else ""))
    return "\n".join(f"{f.key} ({tag(f)}): {f.text}" for f in facts.facts)


TIME_RULES = ("Say historical facts as history with their date ('in December 2021, ...'), forecasts as forecasts "
              "with whose ('the Bank expected ...'), and never present an old figure as today's. General principles "
              "(no figures, names or dates) are claims with kind=principle; your own views are kind=opinion. Never "
              "mention the fact sheet, sources list or these instructions in the narration.")


VISUALS = ("Choose a visual type per scene: chart (only with real numbers from the fact sheet), stat, list, steps, "
           "comparison, quote, title_card or stock (with a short stock_query). For a few scenes where movement explains "
           "the sentence (at most 4 in a long video, 1 in a Short), use type=animated with an animation: "
           "budget_jars (money split into 2-4 parts: items 'Label|amount'), price_basket (prices that change: items "
           "'Item|before|after', 1-4 rows), agent_handoff (AI agents passing a task: items are 2-5 step names) or "
           "counter (one number growing to its value: stat_value plus stat_label). Every number in an animation "
           "must be said in that scene's narration and come from the facts.")
CALCULATIONS = ("Any number you work out yourself (a total, a difference, interest, a percentage) is a claim with "
                "kind=calculation: put the exact arithmetic in expression using only numbers and + - * / ** ( ), "
                "write percentages as decimals (5% -> 0.05), and state every assumption in the claim text, e.g. "
                "'Saving $200 a month for 10 years adds up to $24,000' with expression 200*12*10. Code recalculates "
                "each one: a wrong or unexplained number fails the video.")
SECTION_GUIDE = {
    "problem": "Straight after the hook, show the concrete problem and the result the viewer will get. No greeting.",
    "learn": "Give a short roadmap: exactly what the viewer will learn, in the order the sections below cover it.",
    "body": "Teach this part properly: original reasoning, a worked example or step-by-step demonstration with real "
            "numbers from the fact sheet, and why it matters to the viewer.",
    "limits": "Be honest about the limitations, costs, risks and alternatives. Say when something isn't worth it.",
    "wrap": "Recap the three most useful takeaways, give one practical thing to try today, then the call to action.",
}
SHARE = {"problem": 0.075, "learn": 0.11, "limits": 0.135, "wrap": 0.09}  # the body sections share the rest


def long_minutes() -> dict:
    r = config.services()["render"]
    return {"min": r.get("min_long_minutes", 8), "target": r.get("target_long_minutes", 11),
            "max": r.get("max_long_minutes", 14)}


def _structure(outline: Outline) -> list[OutlineSection]:
    """Always the same clear shape: problem → what you'll learn → 3-5 teaching sections → limits → wrap-up."""
    by_kind = lambda k: [x for x in outline.sections if x.kind == k]
    body = by_kind("body")[:5] or [OutlineSection(name="The main idea", kind="body", purpose=outline.promise)]
    first = lambda k, name, purpose: (by_kind(k) or [OutlineSection(name=name, kind=k, purpose=purpose)])[0]
    return ([first("problem", "The problem", outline.promise), first("learn", "What you'll learn", outline.promise)]
            + body + [first("limits", "Limits and alternatives", "Where this doesn't work and what to do instead"),
                      first("wrap", "Wrap-up", "The takeaways and one thing to try today")])


def draft(router: Router, channel: str, idea: dict, facts: FactSheet, minutes: float | None = None) -> tuple[Script, dict]:
    """An 8-14 minute script written in two passes: an outline with a fixed structure, then each section in turn
    with the whole outline and the end of the previous section in view, so it reads as one clear story."""
    ch = config.brand()["channels"][channel]
    speed = float(ch["voice_profile"].get("tts_speed", 1.0))
    target = minutes or long_minutes()["target"]
    brief = (f"{voice_brief(channel)}\n\nFact sheet (the ONLY facts you may state):\n{_facts_block(facts)}\n"
             f"Background: {facts.context}\n{TIME_RULES}")
    plan = router.complete("scriptwriter", (
        f"Plan the outline of a {target:g}-minute YouTube video: '{idea['title']}'. Angle: {idea.get('angle', '')}\n\n"
        f"{brief}\n\nSections, in this order: one 'problem' section (the concrete problem and the result), one "
        "'learn' section (what the viewer will learn), 3 to 5 'body' sections that each teach one clear step or idea "
        "and build on each other, one 'limits' section (limitations, costs, alternatives), one 'wrap' section "
        "(takeaways and one thing to try today). For each section give its purpose and the fact keys it uses; every "
        "fact should be used once where it fits best. Also give a hook that earns attention in under 15 seconds with "
        "something concrete (no generic question), a one-line promise, 3 alternative hooks and a natural call to action."),
        schema=Outline, temperature=0.7, max_tokens=3000)
    outline = plan.data
    sections = _structure(outline)
    n_body = sum(1 for x in sections if x.kind == "body")
    total = target * 60
    body_seconds = total * (1 - sum(SHARE.values())) / max(n_body, 1)
    plan_text = "\n".join(f"{i}. [{x.kind}] {x.name}: {x.purpose}" for i, x in enumerate(sections, 1))
    wrote = set(plan.companies())
    tokens_in, tokens_out = plan.input_tokens, plan.output_tokens
    scenes: list = []
    claims: list = []
    for i, sec in enumerate(sections, 1):
        seconds = SHARE.get(sec.kind, 0) * total or body_seconds
        words = int(seconds * WORDS_PER_SECOND * speed)
        k = max(1, round(seconds / 35))
        before = " ".join(sc.narration for sc in scenes[-2:]) or f"(The hook has just been spoken: \"{outline.hook}\")"
        res = router.complete("scriptwriter", (
            f"{brief}\n\nVideo: '{outline.title}'. Promise: {outline.promise}\nOutline:\n{plan_text}\n\n"
            f"End of the script so far: {before[-900:]}\n\n"
            f"Write ONLY section {i} of {len(sections)}: '{sec.name}' ({sec.kind}). {SECTION_GUIDE[sec.kind]} "
            f"Purpose: {sec.purpose}. Facts to use here: {', '.join(sec.fact_keys) or 'any that fit'}.\n"
            f"Length: about {words} words of narration in {k} scene(s), each one visual beat of 60-100 words. "
            "Continue naturally from the text above: don't re-introduce the video, don't repeat earlier points, "
            "no filler. " + (f"End with this call to action: {outline.cta} " if sec.kind == "wrap" else "")
            + VISUALS + " List every factual statement in claims (keys C1, C2...) with fact_refs; scenes list the "
            "claim keys they use; mark opinions kind=opinion. " + CALCULATIONS),
            schema=SectionDraft, temperature=0.8, max_tokens=5000, prefer=wrote)
        replies = [res]
        got = sum(len(sc.narration.split()) for sc in res.data.scenes)
        if sec.kind != "wrap" and got < words * SHORT_SECTION:  # free models often stop at half the length asked
            so_far = " ".join(sc.narration for sc in res.data.scenes)
            more = router.complete("scriptwriter", (
                f"{brief}\n\nVideo: '{outline.title}'. Outline:\n{plan_text}\n\nSection {i} ('{sec.name}', {sec.kind}) "
                f"so far:\n{so_far[-2500:]}\n\nIt has {got} words and needs about {words - got} more. Continue this "
                f"section with {max(1, round((words - got) / 80))} more scene(s): go deeper with a worked example, "
                "a concrete step, a comparison or a number from the fact sheet. Don't repeat what it already says, "
                "no filler, don't close the video. " + VISUALS + " List every factual statement in claims (keys C1, "
                "C2...) with fact_refs; mark opinions kind=opinion. " + CALCULATIONS),
                schema=SectionDraft, temperature=0.8, max_tokens=5000, prefer=wrote)
            replies.append(more)
        for r in replies:
            wrote |= r.companies()
            tokens_in, tokens_out = tokens_in + r.input_tokens, tokens_out + r.output_tokens
            rename = {}
            for c in r.data.claims:
                rename[c.key] = f"C{len(claims) + 1}"
                claims.append(c.model_copy(update={"key": rename[c.key]}))
            for sc in r.data.scenes:
                scenes.append(sc.model_copy(update={"claim_keys": [rename[x] for x in sc.claim_keys if x in rename]}))
    script = Script(title=outline.title, hook=outline.hook, promise=outline.promise,
                    hook_candidates=outline.hook_candidates, scenes=scenes, claims=claims, cta=outline.cta)
    return script, {"provider": plan.provider, "model": plan.model, "companies": sorted(wrote),
                    "sections": [x.name for x in sections], "in": tokens_in, "out": tokens_out}


def expansion_targets(script: Script, limit: int = 6) -> list[int]:
    """Scenes to deepen when the video is too short: the shortest teaching scenes, never the opening or the ending."""
    inner = list(range(3, len(script.scenes) - 1)) or list(range(1, len(script.scenes) + 1))
    return sorted(sorted(inner, key=lambda n: len(script.scenes[n - 1].narration.split()))[:limit])


def rewrite_scenes(router: Router, channel: str, script: Script, scene_numbers: list[int], instructions: list[str],
                   facts: FactSheet, prefer: set[str] | None = None) -> tuple[Script, dict]:
    scene_numbers = sorted({n for n in scene_numbers if 1 <= n <= len(script.scenes)})
    if not scene_numbers:
        return script, {}
    target = [script.scenes[n - 1].model_dump() for n in scene_numbers]
    keys = {k for n in scene_numbers for k in script.scenes[n - 1].claim_keys}
    claims = [c.model_dump(include={"key", "text", "kind", "fact_refs", "expression"}) for c in script.claims if c.key in keys]
    before = script.scenes[scene_numbers[0] - 2].narration[-300:] if scene_numbers[0] > 1 else script.hook
    prompt = (f"{voice_brief(channel)}\n\nFact sheet (each fact with its passage and date):\n{_evidence_block(facts)}\n\n"
              f"{TIME_RULES}\n\nRewrite ONLY these scenes of the script '{script.title}' (scene numbers "
              f"{scene_numbers}). Just before them the script says: \"{before}\"\nScenes:\n{json.dumps(target, indent=1)}\n"
              f"Their claims:\n{json.dumps(claims, indent=1)}\n\nFix these problems:\n- " + "\n- ".join(instructions) +
              "\n\nFor a claim that isn't supported: find the fact that supports it and cite it, or qualify it to what "
              "the passage says (with its date or who said it), or remove the statement. Return the corrected claims "
              "too (same keys where the claim stays). " + CALCULATIONS + " "
              f"Return exactly {len(scene_numbers)} scenes in the same order.")
    res = router.complete("scriptwriter", prompt, schema=SceneRewrite, temperature=0.5, prefer=prefer)
    if len(res.data.scenes) != len(scene_numbers):
        return script, res.trail()
    scenes = list(script.scenes)
    for n, new in zip(scene_numbers, res.data.scenes):
        scenes[n - 1] = new
    merged = {c.key: c for c in script.claims}
    for c in res.data.claims:  # corrected or new claims replace the old ones with the same key
        merged[c.key] = c
    script = script.model_copy(update={"scenes": scenes, "claims": repair.prune_claims(scenes, list(merged.values()))})
    return script, res.trail()


def _evidence_block(facts: FactSheet) -> str:
    return "\n".join(f"{f.key} ({f.time_kind}, {f.published or 'date unknown'}"
                     f"{', ' + f.data_period if f.data_period else ''}): {f.text}\n   passage: {f.passage[:300]}"
                     for f in facts.facts)


def voice_edit(router: Router, channel: str, script: Script, writers: set[str]) -> tuple[Script, dict]:
    """A different model rewrites narration in the host's voice. Numbers must survive unchanged."""
    narr = [{"n": i, "narration": s.narration} for i, s in enumerate(script.scenes, 1)]
    prompt = (f"{voice_brief(channel)}\n\nEdit the narration of every scene so it sounds like this host speaking "
              "to one friend: natural rhythm, contractions, varied sentence length, concrete words, no filler, no "
              "generic AI phrasing. Keep every fact and every number exactly. Keep the same meaning and order.\n\n"
              f"Hook: {script.hook}\nScenes:\n{json.dumps(narr, indent=1)}\n\nReturn JSON "
              '{"hook": str, "scenes": [{"n": int, "narration": str}]} with all scenes.')
    from pydantic import BaseModel

    class Edited(BaseModel):
        hook: str
        scenes: list[dict]

    res = router.complete("voice_editor", prompt, schema=Edited, temperature=0.7, exclude=writers,
                          max_tokens=8000)
    edited = {int(s.get("n", 0)): str(s.get("narration", "")) for s in res.data.scenes}
    scenes = []
    for i, sc in enumerate(script.scenes, 1):
        new = edited.get(i, "").strip()
        # code-level guard: reject edits that drop or change numbers
        if new and quality.numbers_in(new) == quality.numbers_in(sc.narration):
            scenes.append(sc.model_copy(update={"narration": new}))
        else:
            scenes.append(sc)
    hook = res.data.hook if quality.numbers_in(res.data.hook) <= quality.numbers_in(script.hook) else script.hook
    return script.model_copy(update={"scenes": scenes, "hook": hook}), res.trail()


def critique(router: Router, channel: str, script: Script, writers: set[str]) -> tuple[CriticReport, dict]:
    numbered = "\n".join(f"Scene {i}: {s.narration}" for i, s in enumerate(script.scenes, 1))
    prompt = (f"You are a tough YouTube script editor for {config.brand()['channels'][channel]['display_name']}. "
              "Score 1-10 for each, using these definitions: hook = the first 15 seconds give a concrete reason to "
              "keep watching; originality = reasoning, examples or comparisons beyond restating the sources; "
              "clarity = one idea at a time, plain words, no contradictions; pacing = no repeated points, no "
              "filler, each scene moves on; value = the viewer can act on it or understands something new. "
              "7 means publishable on that criterion; below 7 name what fails it. List specific fixes naming "
              "scene numbers; in delete give scenes that only repeat or go off topic, in merge give groups of "
              "scenes that say the same thing; weak_scenes are scenes to rewrite.\n\nTitle: {script.title}\n"
              f"Hook: {script.hook}\n{numbered}\nCTA: {script.cta}")
    res = router.complete("critic", prompt, schema=CriticReport, temperature=0.2, exclude=writers)
    return res.data, res.trail()


def pick_hook(router: Router, script: Script, writers: set[str]) -> tuple[Script, dict]:
    options = [script.hook] + [h for h in script.hook_candidates if h.strip()][:3]
    if len(options) < 2:
        return script, {}
    from pydantic import BaseModel

    class Choice(BaseModel):
        best: int
        reason: str

    prompt = ("Pick the hook most likely to keep a viewer watching past 15 seconds without clickbait or false "
              "promises. Options:\n" + "\n".join(f"{i}: {h}" for i, h in enumerate(options)))
    res = router.complete("angle_selector", prompt, schema=Choice, temperature=0.0, exclude=writers)
    idx = res.data.best if 0 <= res.data.best < len(options) else 0
    return script.model_copy(update={"hook": options[idx]}), res.trail()


def write_long(router: Router, channel: str, idea: dict, sources: list[dict]) -> ScriptResult:
    trail: list[dict] = []
    facts, dropped, t = build_fact_sheet(router, idea, sources)
    trail.append({"step": "fact_sheet", **t})
    if len(facts.facts) < MIN_LONG_FACTS:
        # an honest long video needs real material: stop before writing rather than pad or invent
        raise NeedsReview(not_enough_evidence(idea, facts, sources, dropped))
    minutes = planned_minutes(len(facts.facts))
    script, t = draft(router, channel, idea, facts, minutes)
    script = script.model_copy(update={"facts": facts.facts})
    # STRICT independence: every company that writes or edits any text joins `writers`, and no check (claims,
    # critic, hook choice, final review) may use a model from any of them.
    writers: set[str] = set(t["companies"])
    trail.append({"step": "draft", "minutes_planned": minutes, **t})
    return finish_long(router, channel, script, facts, sources, writers, trail, dropped=dropped, minutes=minutes)


def not_enough_evidence(idea: dict, facts: FactSheet, sources: list[dict], dropped: list[str]) -> str:
    off = [d for d in dropped if d.startswith("Not used")]
    return (f"Not enough evidence for an honest long video on '{idea['title']}': {len(facts.facts)} checkable facts "
            f"from {len(sources)} source(s), at least {MIN_LONG_FACTS} needed"
            + (f" ({len(off)} source(s) were off-topic)" if off else "")
            + ". Next: narrow the topic to what the sources cover, or choose an idea with more coverage."
            + (f" The sources do cover: {'; '.join(f.text[:80] for f in facts.facts[:3])}." if facts.facts else ""))[:900]


def _polish(step, trail: list[dict], name: str):
    """A polishing step (voice, hook choice) that can't find a free model is skipped, never failing the package."""
    try:
        return step()
    except (QuotaError, TransientError) as exc:
        trail.append({"step": name, "skipped": str(exc)[:300]})
        return None


def finish_long(router: Router, channel: str, script: Script, facts: FactSheet, sources: list[dict], writers: set[str],
                trail: list[dict], *, dropped: list[str] | None = None, minutes: float | None = None,
                notes: list[str] | None = None) -> ScriptResult:
    """Everything after the first draft, also used to repair an existing script: polish, structural edit, then
    code repairs and targeted rewrites with their recheck, then one final check of the whole script. Bounded: one
    structural edit, REPAIR_ROUNDS rewrites, one final critic."""
    money = channel == "money"
    speed = float(config.brand()["channels"][channel]["voice_profile"].get("tts_speed", 1.0))
    shortest = quality.shortest_long_seconds()
    changes: list[str] = list(notes or [])

    edited = _polish(lambda: voice_edit(router, channel, script, writers), trail, "voice_edit")
    if edited:
        script, t = edited
        writers |= set(t["companies"])
        trail.append({"step": "voice_edit", **t})
    script, ch = code_repairs(script, money)
    changes += ch

    # structural edit from the critic: remove repetition and off-topic scenes, merge duplicates, rewrite weak ones
    critic = _polish(lambda: critique(router, channel, script, writers), trail, "critic")
    if critic:
        report, t = critic
        trail.append({"step": "critic", **t})
        if report.minimum() < CRITIC_MIN and (report.delete or report.merge or report.weak_scenes):
            # as many of the critic's cuts as keep the video long enough (in the critic's order), merges always
            merged_at = []
            for k in range(len(report.delete), -1, -1):
                scenes, merged_at, ch = repair.apply_edit_plan(script.scenes, report.delete[:k], report.merge)
                if len(scenes) >= MIN_SCENES and sum(quality.est_seconds(sc.narration, speed) for sc in scenes) >= shortest:
                    script = script.model_copy(update={"scenes": scenes, "claims": repair.prune_claims(scenes, script.claims)})
                    changes += ch
                    if k < len(report.delete):
                        changes.append(f"Applied {k} of the critic's {len(report.delete)} suggested cuts: all of them "
                                       "would have made the video too short")
                    break
            else:
                merged_at = []
                changes.append("Didn't apply the critic's suggested cuts: the video would have become too short")
            redo = sorted(set(merged_at) | {n for n in report.weak_scenes if 1 <= n <= len(script.scenes)
                                           and not report.delete})
            if redo:
                script, t = rewrite_scenes(router, channel, script, redo[:8], report.fixes or ["Make this scene "
                                           "flow from the one before, without repeating it"], facts, prefer=writers)
                writers |= set(t.get("companies", []))
                trail.append({"step": "critic_fix", **t})
            script, ch = code_repairs(script, money)
            changes += ch

    # repair until the checks pass or the rounds run out: code fixes first, then rewrite only the failing scenes
    claims: list[dict] = []
    for round_no in range(REPAIR_ROUNDS + 1):
        claims = verify.check_claims(router, script, facts, sources, exclude=writers)
        script, ch = repair.fix_calculations(script, claims)
        script, ch2 = repair.qualify_stale(script, claims)
        ch += ch2
        if ch:
            changes += ch
            claims = verify.check_claims(router, script, facts, sources, exclude=writers)
        issues = quality.check_long(script, channel, min_seconds=shortest)
        bad = [c for c in claims if c["status"] in repair.BAD]
        if round_no == REPAIR_ROUNDS or (not bad and not blocking(issues)):
            break
        targets, instructions = scenes_to_fix(script, bad, issues)
        if not targets:
            break
        script, t = rewrite_scenes(router, channel, script, targets[:8], instructions, facts, prefer=writers)
        writers |= set(t.get("companies", []))
        trail.append({"step": f"repair_{round_no + 1}", "scenes": targets[:8], **t})
        script, ch = code_repairs(script, money)
        changes += ch

    # last resort: a scene that still states something nobody can back is removed, if the video stays long enough
    script, ch, unresolved = repair.drop_unsupported_scenes(script, claims, shortest, speed)
    if ch:
        changes += ch
        claims = verify.check_claims(router, script, facts, sources, exclude=writers)
    picked = _polish(lambda: pick_hook(router, script, writers), trail, "hook_pick")
    if picked:
        script, t = picked
        if t:
            trail.append({"step": "hook_pick", **t})
    script = script.model_copy(update={
        "scenes": [sc.model_copy(update={"narration": quality.remove_banned(sc.narration)}) for sc in script.scenes],
        "hook": quality.remove_banned(script.hook), "cta": quality.remove_banned(script.cta), "facts": facts.facts})

    # final consistency check of the exact version that will be saved
    final = _polish(lambda: critique(router, channel, script, writers), trail, "critic_final")
    report = final[0] if final else None
    if final:
        trail.append({"step": "critic_final", **final[1]})
    issues = quality.check_long(script, channel, min_seconds=shortest)
    findings = classify(issues, claims, report, script, speed, changes)
    rep = {"critic": report.model_dump() if report else None, "issues": [f["text"] for f in findings
                                                                        if f["kind"] in ("blocker", "warning")],
           "findings": findings, "dropped_facts": dropped or [], "repairs": changes,
           "claims": {st: sum(1 for c in claims if c["status"] == st) for st in {c["status"] for c in claims}},
           "duration_seconds": script.duration(speed), "minutes_planned": minutes, "writers": sorted(writers),
           "stats": quality.sentence_stats(script.full_text())}
    return ScriptResult(script, facts, claims, [f["text"] for f in findings if f["kind"] == "blocker"], rep, trail)


PLAIN = {"1", "2", "3", "4", "5", "10"}


def post_number_problems(pkg: Package, facts: FactSheet) -> list[str]:
    """Post texts may only state numbers the checked facts give (or their dates): a number in a Facebook or X post is
    as public as one in the video."""
    known = set().union(*[quality.numbers_in(f.text) for f in facts.facts]) if facts.facts else set()
    known |= evidence.date_numbers(facts.facts) | PLAIN
    out = []
    for name, text in (("X post", pkg.x_post), ("Facebook post", pkg.facebook_post), ("YouTube title", pkg.youtube_title)):
        stray = sorted(quality.figures_in(text or "") - known)
        if stray:
            out.append(f"{name} states numbers not in the evidence: {stray}")
    return out


def package_findings(problems: list[str]) -> list[dict]:
    """Package notes by kind: a Short that couldn't be made is a missing part; a title tag or a repair is info."""
    out = []
    for p in problems:
        if " dropped:" in p:
            out.append({"kind": "missing", "code": "short_dropped", "text": p})
        elif "states numbers not in the evidence" in p:
            out.append({"kind": "blocker", "code": "post_numbers", "text": p})
        elif p.startswith(("Title marked", "Short '")) or "repaired" in p or "trimmed" in p or p.startswith("Removed"):
            out.append({"kind": "info", "code": "package", "text": p})
        else:
            out.append({"kind": "warning", "code": "package", "text": p})
    return out


def code_repairs(script: Script, money: bool) -> tuple[Script, list[str]]:
    """The fixes code can decide on its own: claim links, repeated sentences and disclaimers, animation labels."""
    script, a = repair.fix_claim_links(script)
    script, w = repair.remove_spoken_working(script)
    a += w
    script, b = repair.remove_repeats(script, money)
    scenes, c = repair.fix_animations(script.scenes)
    return script.model_copy(update={"scenes": scenes}), a + b + c


BLOCKING = ("Too short", "Needs 6-40 scenes", "Claims a hands-on test", "states numbers", "references unknown claims",
            "Promises returns", "Money script must say", "Too long", "Too similar", "Title too close")


def blocking(issues: list[str]) -> list[str]:
    return [i for i in issues if any(i.startswith(b) or b in i for b in BLOCKING)]


def scenes_to_fix(script: Script, bad: list[dict], issues: list[str]) -> tuple[list[int], list[str]]:
    """Only the scenes that carry a failing claim or are named by a failing check, with what to do about each."""
    targets: set[int] = set()
    notes = []
    for i, sc in enumerate(script.scenes, 1):
        if any(c["key"] in sc.claim_keys for c in bad):
            targets.add(i)
    for c in bad:
        what = {"stale": "say when it applied", "contradicted": "correct it to what the evidence says"}.get(
            c["status"], "cite the fact that supports it, qualify it to the passage, or remove it")
        notes.append(f"Claim {c['key']} '{c['text'][:160]}' is {c['status']} ({c['note'][:160]}): {what}")
    import re as _re

    for i in issues:
        m = _re.match(r"Scene (\d+) ", i)
        if m and i in blocking(issues):
            targets.add(int(m.group(1)))
            notes.append(i)
    return sorted(targets), notes


def classify(issues: list[str], claims: list[dict], report: CriticReport | None, script: Script, speed: float,
             changes: list[str]) -> list[dict]:
    """Four kinds, never mixed: blocker (a factual problem: it can't go out like this), warning (editorial: a person
    should look), missing (a part that wasn't made) and info (what the studio changed or noticed)."""
    out = []
    for c in claims:
        if c["status"] in repair.BAD:
            label = {"stale": "Old figure said as current", "contradicted": "Contradicted by its source"}.get(
                c["status"], "Not backed by a source")
            out.append({"kind": "blocker", "code": f"claim_{c['status']}", "text": f"{label}: \"{c['text'][:140]}\"",
                        "detail": c["note"][:200]})
    for i in issues:
        out.append({"kind": "blocker" if i in blocking(issues) else "warning", "code": "check", "text": i})
    if report is None:
        out.append({"kind": "warning", "code": "critic_unavailable",
                    "text": "Editorial score unavailable (no independent editor model was free): read it through"})
    elif report.minimum() < CRITIC_MIN:
        low = {k: v for k, v in report.model_dump(include={"hook", "originality", "clarity", "pacing", "value"}).items()
               if v < CRITIC_MIN}
        out.append({"kind": "warning", "code": "critic_low", "text": f"Editor scores below {CRITIC_MIN}: {low}",
                    "detail": "; ".join(report.fixes[:3])})
    secs = script.duration(speed)
    if secs < quality.MIN_LONG_SECONDS:
        out.append({"kind": "info", "code": "shorter_video", "text": f"About {secs / 60:.1f} minutes: that's what the "
                    "evidence supports (YouTube shows mid-video ads from 8 minutes)"})
    for ch in changes:
        out.append({"kind": "info", "code": "repair", "text": ch})
    return out


SHORTS_BRIEF = ("two purpose-built Shorts that each tell a complete mini-story from the facts. EACH Short is 35-55 "
                "seconds: 90-130 spoken words counting its hook and all its scenes (so 3-6 scenes of 20-30 words). "
                "Short sentences of at most 16 words. Give each Short a YouTube caption, a different shorter tiktok_caption "
                "and a different reel_caption for Facebook (each says what the viewer learns, no clickbait, no "
                "'link in bio'), and 3-5 hashtags about the topic itself, never unrelated trending tags. "
                "Only use facts listed.")


class ShortsOnly(BaseModel):
    shorts: list[ShortScript]


def check_shorts(shorts: list[ShortScript], channel: str, facts: FactSheet) -> tuple[list[ShortScript], list[str], list[dict]]:
    """Shorts that pass every check, a plain line per dropped one, and the dropped ones with their reasons."""
    fact_numbers = set().union(*[quality.numbers_in(f.text) for f in facts.facts]) if facts.facts else set()
    good, problems, dropped = [], [], []
    for s in shorts:
        issues = quality.check_short(s, channel)
        stray = set().union(*[quality.figures_in(sc.narration) for sc in s.scenes]) - fact_numbers - {"1", "2", "3", "4", "5"}
        if stray:
            issues.append(f"Short uses numbers not in the fact sheet: {sorted(stray)}")
        if issues:
            problems.append(f"Short '{s.title}' dropped: {issues}")
            dropped.append({"title": s.title, "issues": issues})
        else:
            good.append(s)
    return good, problems, dropped


def make_shorts(router: Router, channel: str, script: Script, facts: FactSheet, tries: int = 2,
                note: str = "") -> tuple[list[ShortScript], list[str], list[dict]]:
    """Only the Shorts, from the video's own checked facts. Each try that yields no usable Short says why and tries
    again, up to `tries` times. Returns the good Shorts, the problems and every dropped Short."""
    problems: list[str] = []
    dropped: list[dict] = []
    for n in range(1, tries + 1):
        reasons = "; ".join(f"'{d['title']}': {', '.join(d['issues'])}" for d in dropped[-2:])
        prompt = (f"{voice_brief(channel)}\n\nWrite {SHORTS_BRIEF}\nVideo title: {script.title}\nHook: {script.hook}\n"
                  f"Facts you may use:\n{_facts_block(facts)}\n"
                  + (f"\nThe last Shorts were rejected because: {reasons}. Fix exactly that.\n" if reasons else "")
                  + (f"\nOwner note: {note}\n" if note else ""))
        res = router.complete("repurposer", prompt, schema=ShortsOnly, temperature=0.7, max_tokens=3000)
        good, why, out = check_shorts(res.data.shorts, channel, facts)
        # a Short that failed on length or sentence size is repaired on its own, not thrown away
        for d, short in [(d, sh) for d in out for sh in res.data.shorts if sh.title == d["title"]]:
            fixed = repair_short(router, channel, short, d["issues"], facts)
            if fixed is not None:
                good.append(fixed)
                why = [w for w in why if f"'{short.title}'" not in w]
                out = [x for x in out if x is not d]
        problems += [f"Retry {n}: {w}" for w in why]
        dropped += out
        if good:
            return good, problems, dropped
    built = shorts_from_script(script, channel, facts)
    if built:
        problems.append(f"Short '{built[0].title}' repaired: made from the checked script's own sentences "
                        "(the written Shorts were too thin)")
    return built, problems, dropped


SHORT_WORDS = (90, 130)
SHORT_SENTENCE = 18  # longest sentence taken into a Short


def shorts_from_script(script: Script, channel: str, facts: FactSheet, n: int = 2) -> list[ShortScript]:
    """Shorts built from the main video's checked sentences when the written ones keep failing: consecutive scenes'
    short sentences, 90-130 words, kept only if they pass every Short check (numbers from the facts included).
    Nothing new is claimed, so nothing new needs checking."""
    out: list[ShortScript] = []
    used: set[int] = set()
    body = list(range(1, len(script.scenes) - 1)) or list(range(len(script.scenes)))
    for start in body:
        if len(out) >= n or start in used:
            continue
        picked, words, keys, visuals = [], 0, [], []
        for i in range(start, len(script.scenes)):
            if i in used:
                break
            sc = script.scenes[i]
            for sent in re.split(r"(?<=[.!?])\s+", sc.narration.strip()):
                w = len(sent.split())
                if 4 <= w <= SHORT_SENTENCE and words + w <= SHORT_WORDS[1]:
                    picked.append((i, sent))
                    words += w
            keys += sc.claim_keys
            visuals.append(sc.visual)
            if words >= SHORT_WORDS[0]:
                break
        if words < SHORT_WORDS[0] or len(picked) < 5:
            continue
        hook, rest = picked[0][1], picked[1:]
        groups = [rest[k:k + max(2, len(rest) // 4)] for k in range(0, len(rest), max(2, len(rest) // 4))][:6]
        scenes = []
        for g in groups:
            src = script.scenes[g[0][0]]
            scenes.append(Scene(narration=" ".join(x[1] for x in g), visual=src.visual,
                                claim_keys=list(dict.fromkeys(k for j, _ in g for k in script.scenes[j].claim_keys))))
        short = ShortScript(title=(hook.rstrip(".!?")[:60] or script.title[:60]), hook=hook, scenes=scenes,
                            caption=hook[:150], hashtags=["money" if channel == "money" else "ai"],
                            tiktok_caption=hook[:100], reel_caption=hook[:150])
        good, _, _ = check_shorts([short], channel, facts)
        if good:
            out.append(good[0])
            used |= {j for j, _ in picked}
    return out


SHORT_REPAIRS = 2


def repair_short(router: Router, channel: str, short: ShortScript, issues: list[str], facts: FactSheet) -> ShortScript | None:
    """Fix one Short's own problems (too thin, too long, long sentences, a stray number), keeping its story. Returns
    the fixed Short when it passes every check, else None. Never touches the main video."""
    for _ in range(SHORT_REPAIRS):
        speed = float(config.brand()["channels"][channel]["voice_profile"].get("tts_speed", 1.0))
        secs = sum(quality.est_seconds(s.narration, speed) for s in short.scenes) + quality.est_seconds(short.hook, speed)
        prompt = (f"{voice_brief(channel)}\n\nFacts you may use:\n{_facts_block(facts)}\n\nThis Short (about "
                  f"{secs:.0f} seconds now) failed these checks: {'; '.join(issues)}.\n{short.model_dump_json(indent=1)}\n\n"
                  "Fix exactly that and keep its story: it must be 90-130 spoken words in total (35-55 seconds), "
                  "3-6 scenes, sentences of at most 16 words, and only numbers from the facts. Return the Short.")
        try:
            res = router.complete("repurposer", prompt, schema=ShortScript, temperature=0.5, max_tokens=2000)
        except (QuotaError, TransientError):
            return None
        short = res.data
        good, _, out = check_shorts([short], channel, facts)
        if good:
            return good[0]
        issues = out[0]["issues"] if out else issues
    return None


STUFFING_LIMIT = 3  # the main search phrase more often than this in one description reads as keyword stuffing


def search_problems(pkg: Package) -> list[str]:
    """Keyword stuffing and a brief that isn't used: plain notes for Review (they never change the text)."""
    b = pkg.search_brief
    if not b or not b.primary_phrase.strip():
        return []
    phrase = b.primary_phrase.strip().lower()
    out = []
    n = pkg.youtube_description.lower().count(phrase)
    if n > STUFFING_LIMIT:
        out.append(f"The search phrase \"{b.primary_phrase}\" appears {n} times in the description (keyword stuffing: use it once or twice)")
    tags = [t.lower() for t in pkg.tags]
    if sum(phrase in t for t in tags) > 3:
        out.append(f"Too many tags repeat \"{b.primary_phrase}\"; vary them with the supporting phrases")
    return out


def make_package(router: Router, channel: str, script: Script, facts: FactSheet,
                 hints: str = "") -> tuple[Package, list[str], dict]:
    ch = config.brand()["channels"][channel]
    prompt = (f"{voice_brief(channel)}\n\nCreate the publishing package for this video.\nTitle: {script.title}\n"
              f"Hook: {script.hook}\nSummary: {script.promise}\nFacts you may use:\n{_facts_block(facts)}\n\n"
              "- youtube_title: under 70 chars, specific and honest (no clickbait).\n"
              "- youtube_description: 3 short paragraphs + 'Sources:' line placeholder [SOURCES].\n"
              "- tags: 10-15 search phrases.\n- thumbnail_headlines: three different 2-5 word texts.\n"
              "- x_post: under 270 characters, no links, one insight + a question.\n"
              f"- facebook_post: 60-120 words for the {config.brand()['brand']['name']} page.\n"
              f"- shorts: {SHORTS_BRIEF}\n"
              "- search_brief: the intended audience, the question they would type into YouTube or Google, one primary "
              "search phrase (2-5 words) and 3-6 supporting phrases. Base it on the topic and facts only; you have no "
              "search-volume data, so never claim volumes or that a topic is trending. Use the primary phrase naturally "
              "in youtube_title and the first sentence of youtube_description, and the supporting phrases in tags. "
              "Write each platform's text for that platform; don't copy the same words everywhere."
              + (f"\n\nYour own past results (real numbers from this channel):\n{hints}" if hints else ""))
    res = router.complete("repurposer", prompt, schema=Package, temperature=0.8, max_tokens=6000)
    pkg = res.data
    good_shorts, problems, failed = check_shorts(pkg.shorts, channel, facts)
    for d in failed:  # repair each failed Short on its own before anything is regenerated
        short = next((sh for sh in pkg.shorts if sh.title == d["title"]), None)
        fixed = repair_short(router, channel, short, d["issues"], facts) if short else None
        if fixed is not None:
            good_shorts.append(fixed)
            problems = [p for p in problems if f"'{d['title']}'" not in p] + [f"Short '{d['title']}' repaired: {', '.join(d['issues'])}"]
    problems += search_problems(pkg)
    problems += post_number_problems(pkg, facts)
    if not good_shorts:  # both failed the checks: one focused retry before giving up
        retry, retry_problems, _ = make_shorts(router, channel, script, facts, tries=1)
        problems += retry_problems
        good_shorts = retry
    if len(pkg.x_post) > 280 or "http" in pkg.x_post.lower() or "www." in pkg.x_post.lower():
        problems.append("X post too long or contains a link; trimmed")
        pkg.x_post = pkg.x_post.split("http")[0][:270].strip()
    if ch.get("disclaimer") and "not personal" not in pkg.youtube_description.lower():
        pkg.youtube_description += "\n\n" + ch["disclaimer"].strip()
    disclosure = (config.services().get("publishing", {}).get("ai_disclosure") or {}).get("description_line")
    if disclosure and disclosure not in pkg.youtube_description:
        pkg.youtube_description += "\n\n" + disclosure
    pkg.shorts = good_shorts
    for field_name in ("youtube_title", "youtube_description", "x_post", "facebook_post"):
        setattr(pkg, field_name, quality.remove_banned(getattr(pkg, field_name)))
    # never claim a hands-on test: a bad title falls back to the checked script title, other texts lose the sentence
    if quality.invented_tests(pkg.youtube_title):
        problems.append(f"Title claimed a hands-on test; using the script title instead ('{pkg.youtube_title}')")
        pkg.youtube_title = script.title[:100]
    for field_name in ("youtube_description", "x_post", "facebook_post"):
        text = getattr(pkg, field_name)
        if quality.invented_tests(text):
            setattr(pkg, field_name, quality.drop_invented_tests(text))
            problems.append(f"Removed a claimed hands-on test from the {field_name.replace('_', ' ')}")
    # a money video built on one country's rules says so in its title, e.g. "Credit scores explained (US)"
    if channel == "money":
        country = quality.main_country(script.full_text() + " " + script.title)
        tagged = quality.with_country(pkg.youtube_title, country)
        if tagged != pkg.youtube_title:
            problems.append(f"Title marked as {country}-specific")
            pkg.youtube_title = tagged
    return pkg, problems, res.trail()
