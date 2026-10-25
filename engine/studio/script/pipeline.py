"""Adaptive multi-model script pipeline.

evidence -> draft once -> structure gate -> claim check -> voice edit -> critic ->
targeted rewrites (max 2) -> final gates. Uncertain results go to human review instead of
looping forever.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from .. import config
from ..ai.router import Router
from ..errors import NeedsReview
from ..research.engine import source_block
from . import quality, verify
from .models import (WORDS_PER_SECOND, CriticReport, FactSheet, Outline, OutlineSection, Package, SceneRewrite,
                     Script, SectionDraft, ShortScript)

MAX_REWRITES = 2
CRITIC_MIN = 7
MIN_LONG_FACTS = 10   # checkable facts an 8-14 minute video needs; fewer means padding or invention
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
        return bool(self.issues) or any(c["status"] in ("unsupported", "contradicted") for c in self.claims)


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
    # each source's full article text is shown, within a budget the free models can read in one go
    per_source = max(1500, min(6000, 30000 // max(len(sources), 1)))
    prompt = (f"Video idea: {idea['title']}\nAngle: {idea.get('angle', '')}\n\nSources:\n"
              f"{source_block(sources, body_chars=per_source)}\n\n"
              f"Extract {FACTS_WANTED} short factual statements that are directly stated in the sources, each citing its "
              "source label (S1...). Prefer specific, useful facts: numbers, dates, names, how something works, "
              "what changed and who it affects. Keep numbers exactly as written and note the period the data covers. "
              "Do not add anything the sources do not say.")
    res = router.complete("research_summarizer", prompt, schema=FactSheet, temperature=0.1, max_tokens=4000)
    grounded, dropped = verify.ground_facts(res.data, sources)
    return grounded, dropped, res.trail()


def _facts_block(facts: FactSheet) -> str:
    return "\n".join(f"{f.key} ({f.source_ref}{', ' + f.data_period if f.data_period else ''}): {f.text}"
                     for f in facts.facts)


VISUALS = ("Choose a visual type per scene: chart (only with real numbers from the fact sheet), stat, list, steps, "
           "comparison, quote, title_card or stock (with a short stock_query).")
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


def draft(router: Router, channel: str, idea: dict, facts: FactSheet) -> tuple[Script, dict]:
    """An 8-14 minute script written in two passes: an outline with a fixed structure, then each section in turn
    with the whole outline and the end of the previous section in view, so it reads as one clear story."""
    ch = config.brand()["channels"][channel]
    speed = float(ch["voice_profile"].get("tts_speed", 1.0))
    mins = long_minutes()
    brief = f"{voice_brief(channel)}\n\nFact sheet (the ONLY facts you may state):\n{_facts_block(facts)}\nBackground: {facts.context}"
    plan = router.complete("scriptwriter", (
        f"Plan the outline of a {mins['target']}-minute YouTube video: '{idea['title']}'. Angle: {idea.get('angle', '')}\n\n"
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
    total = mins["target"] * 60
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
    prompt = (f"{voice_brief(channel)}\n\nFact sheet:\n{_facts_block(facts)}\n\nRewrite ONLY these scenes of the "
              f"script '{script.title}' (scene numbers {scene_numbers}):\n{json.dumps(target, indent=1)}\n\n"
              f"Fix these problems:\n- " + "\n- ".join(instructions) +
              "\n\nKeep claim_keys valid. If a fact cannot be supported, remove that statement. " + CALCULATIONS + " "
              f"Return exactly {len(scene_numbers)} scenes in the same order.")
    res = router.complete("scriptwriter", prompt, schema=SceneRewrite, temperature=0.6, prefer=prefer)
    if len(res.data.scenes) != len(scene_numbers):
        return script, res.trail()
    scenes = list(script.scenes)
    for n, new in zip(scene_numbers, res.data.scenes):
        scenes[n - 1] = new
    return script.model_copy(update={"scenes": scenes}), res.trail()


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
              f"Score 1-10 for hook, originality, clarity, pacing and value. Be honest: 7 means publishable. "
              f"List specific fixes naming scene numbers, and weak_scenes.\n\nTitle: {script.title}\n"
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
        # an honest 8-14 minute video needs real material: stop before writing rather than pad or invent
        raise NeedsReview(f"Not enough source material for an honest 8-14 minute video on '{idea['title']}': "
                          f"{len(facts.facts)} checkable facts from {len(sources)} source(s), at least {MIN_LONG_FACTS} "
                          f"needed. Choose an idea with more coverage. Dropped: {dropped}"[:900])
    script, t = draft(router, channel, idea, facts)
    # STRICT independence: every company that writes or edits any text joins `writers`, and no check (claims,
    # critic, hook choice, final review) may use a model from any of them.
    writers: set[str] = set(t["companies"])
    trail.append({"step": "draft", **t})

    for round_no in range(MAX_REWRITES + 1):
        issues = quality.check_long(script, channel)
        claims = verify.check_claims(router, script, facts, sources, exclude=writers)
        bad = [c for c in claims if c["status"] in ("unsupported", "contradicted")]
        if round_no == MAX_REWRITES or (not issues and not bad):
            break
        targets, notes = [], []
        for i, sc in enumerate(script.scenes, 1):
            if any(c["key"] in sc.claim_keys for c in bad):
                targets.append(i)
        notes += [f"Claim {c['key']} '{c['text']}' is {c['status']} ({c['note']}): fix the number or its arithmetic, "
                  "or remove the statement" for c in bad]
        notes += issues
        if any(x.startswith("Too short") for x in issues):
            notes.append("The video is too short: make each of these scenes about 90-100 words by adding a worked "
                         "example, a concrete step or a number from the fact sheet. No padding, no repetition.")
            targets = sorted(set(targets) | set(expansion_targets(script)))
        if not targets:
            targets = [1, len(script.scenes)] if issues else []
        script, t = rewrite_scenes(router, channel, script, targets, notes, facts, prefer=writers)
        writers |= set(t.get("companies", []))
        trail.append({"step": f"fix_round_{round_no + 1}", **t})

    script, t = voice_edit(router, channel, script, writers)
    writers |= set(t["companies"])
    trail.append({"step": "voice_edit", **t})
    report, t = critique(router, channel, script, writers)
    trail.append({"step": "critic", **t})
    if report.minimum() < CRITIC_MIN and report.weak_scenes:
        script, t = rewrite_scenes(router, channel, script, report.weak_scenes, report.fixes, facts, prefer=writers)
        writers |= set(t.get("companies", []))
        trail.append({"step": "critic_fix", **t})
        report, t = critique(router, channel, script, writers)
        trail.append({"step": "critic_recheck", **t})
    script, t = pick_hook(router, script, writers)
    if t:
        trail.append({"step": "hook_pick", **t})

    # last-resort cleanup of banned phrases, then final gates
    script = script.model_copy(update={
        "scenes": [s.model_copy(update={"narration": quality.remove_banned(s.narration)}) for s in script.scenes],
        "hook": quality.remove_banned(script.hook), "cta": quality.remove_banned(script.cta)})
    claims = verify.check_claims(router, script, facts, sources, exclude=writers)
    issues = quality.check_long(script, channel)
    if report.minimum() < CRITIC_MIN:
        issues.append(f"Critic score below {CRITIC_MIN}: {report.model_dump(exclude={'fixes', 'weak_scenes'})}")
    rep = {"critic": report.model_dump(), "issues": issues, "dropped_facts": dropped,
           "claims": {s: sum(1 for c in claims if c["status"] == s) for s in {c["status"] for c in claims}},
           "duration_seconds": script.duration(), "writers": sorted(writers), "stats": quality.sentence_stats(script.full_text())}
    return ScriptResult(script, facts, claims, issues, rep, trail)


def make_package(router: Router, channel: str, script: Script, facts: FactSheet) -> tuple[Package, list[str], dict]:
    ch = config.brand()["channels"][channel]
    prompt = (f"{voice_brief(channel)}\n\nCreate the publishing package for this video.\nTitle: {script.title}\n"
              f"Hook: {script.hook}\nSummary: {script.promise}\nFacts you may use:\n{_facts_block(facts)}\n\n"
              "- youtube_title: under 70 chars, specific and honest (no clickbait).\n"
              "- youtube_description: 3 short paragraphs + 'Sources:' line placeholder [SOURCES].\n"
              "- tags: 10-15 search phrases.\n- thumbnail_headlines: three different 2-5 word texts.\n"
              "- x_post: under 270 characters, no links, one insight + a question.\n"
              f"- facebook_post: 60-120 words for the {config.brand()['brand']['name']} page.\n"
              "- shorts: two purpose-built Shorts (35-55 seconds each) that each tell a complete mini-story from "
              "the facts, with their own hook, 3-6 scenes, a caption and 3-5 hashtags. Only use facts listed.")
    res = router.complete("repurposer", prompt, schema=Package, temperature=0.8, max_tokens=6000)
    pkg = res.data
    problems = []
    fact_numbers = set().union(*[quality.numbers_in(f.text) for f in facts.facts]) if facts.facts else set()
    good_shorts: list[ShortScript] = []
    for s in pkg.shorts:
        issues = quality.check_short(s, channel)
        stray = set().union(*[quality.numbers_in(sc.narration) for sc in s.scenes]) - fact_numbers - {"1", "2", "3", "4", "5"}
        if stray:
            issues.append(f"Short uses numbers not in the fact sheet: {sorted(stray)}")
        if issues:
            problems.append(f"Short '{s.title}' dropped: {issues}")
        else:
            good_shorts.append(s)
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
