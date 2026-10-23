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
from .models import CriticReport, FactSheet, Package, SceneRewrite, Script, ShortScript

MAX_REWRITES = 2
CRITIC_MIN = 7


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
    lines = [f"Host: {ch['host_persona'].strip()}", f"Tone: {', '.join(vp['tone'])}", "Style rules:"]
    lines += [f"- {r}" for r in vp["style_rules"]]
    lines.append(f"Signature phrases (use at most one, naturally): {', '.join(vp.get('signature_phrases', []))}")
    lines.append(f"Never use these phrases: {banned}")
    if ch.get("disclaimer"):
        lines.append(f"Include this idea naturally near the start or end: {ch['disclaimer'].strip()}")
    return "\n".join(lines)


def build_fact_sheet(router: Router, idea: dict, sources: list[dict]) -> tuple[FactSheet, list[str], dict]:
    prompt = (f"Video idea: {idea['title']}\nAngle: {idea.get('angle', '')}\n\nSources:\n{source_block(sources)}\n\n"
              "Extract 6-15 short factual statements that are directly stated in the sources, each citing its "
              "source label (S1...). Keep numbers exactly as written and note the period the data covers. "
              "Do not add anything the sources do not say.")
    res = router.complete("research_summarizer", prompt, schema=FactSheet, temperature=0.1)
    grounded, dropped = verify.ground_facts(res.data, sources)
    return grounded, dropped, res.trail()


def _facts_block(facts: FactSheet) -> str:
    return "\n".join(f"{f.key} ({f.source_ref}{', ' + f.data_period if f.data_period else ''}): {f.text}"
                     for f in facts.facts)


def draft(router: Router, channel: str, idea: dict, facts: FactSheet) -> tuple[Script, dict]:
    prompt = (
        f"Write a YouTube script for '{idea['title']}'. Angle: {idea.get('angle', '')}\n\n"
        f"{voice_brief(channel)}\n\nFact sheet (the ONLY facts you may state):\n{_facts_block(facts)}\n"
        f"Background: {facts.context}\n\n"
        "Structure: a hook that earns attention in under 15 seconds with something concrete; a one-line promise; "
        "8-16 scenes that build a logical story with original explanation, examples and the 'so what'; clear "
        "transitions; a useful conclusion; a natural call to action. Aim for 900-1200 words of narration. "
        "Each scene is one visual beat (max ~40 seconds). Choose a visual type per scene: chart (only with real "
        "numbers from the fact sheet), stat, list, steps, comparison, quote, title_card or stock (with a short "
        "stock_query). Every factual statement must be listed in claims with fact_refs, and scenes list the claim "
        "keys they use. Mark opinions as kind=opinion. Give 3 alternative hooks in hook_candidates."
    )
    res = router.complete("scriptwriter", prompt, schema=Script, temperature=0.8, max_tokens=8000)
    return res.data, res.trail()


def rewrite_scenes(router: Router, channel: str, script: Script, scene_numbers: list[int], instructions: list[str],
                   facts: FactSheet, exclude: str | None = None) -> tuple[Script, dict]:
    scene_numbers = sorted({n for n in scene_numbers if 1 <= n <= len(script.scenes)})
    if not scene_numbers:
        return script, {}
    target = [script.scenes[n - 1].model_dump() for n in scene_numbers]
    prompt = (f"{voice_brief(channel)}\n\nFact sheet:\n{_facts_block(facts)}\n\nRewrite ONLY these scenes of the "
              f"script '{script.title}' (scene numbers {scene_numbers}):\n{json.dumps(target, indent=1)}\n\n"
              f"Fix these problems:\n- " + "\n- ".join(instructions) +
              "\n\nKeep claim_keys valid. If a fact cannot be supported, remove that statement. "
              f"Return exactly {len(scene_numbers)} scenes in the same order.")
    res = router.complete("scriptwriter", prompt, schema=SceneRewrite, temperature=0.6,
                          exclude={exclude} if exclude else None)
    if len(res.data.scenes) != len(scene_numbers):
        return script, res.trail()
    scenes = list(script.scenes)
    for n, new in zip(scene_numbers, res.data.scenes):
        scenes[n - 1] = new
    return script.model_copy(update={"scenes": scenes}), res.trail()


def voice_edit(router: Router, channel: str, script: Script, writer_provider: str) -> tuple[Script, dict]:
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

    res = router.complete("voice_editor", prompt, schema=Edited, temperature=0.7, exclude={writer_provider},
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


def critique(router: Router, channel: str, script: Script, writer_provider: str) -> tuple[CriticReport, dict]:
    numbered = "\n".join(f"Scene {i}: {s.narration}" for i, s in enumerate(script.scenes, 1))
    prompt = (f"You are a tough YouTube script editor for {config.brand()['channels'][channel]['display_name']}. "
              f"Score 1-10 for hook, originality, clarity, pacing and value. Be honest: 7 means publishable. "
              f"List specific fixes naming scene numbers, and weak_scenes.\n\nTitle: {script.title}\n"
              f"Hook: {script.hook}\n{numbered}\nCTA: {script.cta}")
    res = router.complete("critic", prompt, schema=CriticReport, temperature=0.2, exclude={writer_provider})
    return res.data, res.trail()


def pick_hook(router: Router, script: Script) -> tuple[Script, dict]:
    options = [script.hook] + [h for h in script.hook_candidates if h.strip()][:3]
    if len(options) < 2:
        return script, {}
    from pydantic import BaseModel

    class Choice(BaseModel):
        best: int
        reason: str

    prompt = ("Pick the hook most likely to keep a viewer watching past 15 seconds without clickbait or false "
              "promises. Options:\n" + "\n".join(f"{i}: {h}" for i, h in enumerate(options)))
    res = router.complete("angle_selector", prompt, schema=Choice, temperature=0.0)
    idx = res.data.best if 0 <= res.data.best < len(options) else 0
    return script.model_copy(update={"hook": options[idx]}), res.trail()


def write_long(router: Router, channel: str, idea: dict, sources: list[dict]) -> ScriptResult:
    trail: list[dict] = []
    facts, dropped, t = build_fact_sheet(router, idea, sources)
    trail.append({"step": "fact_sheet", **t})
    if len(facts.facts) < 3:
        raise NeedsReview(f"Not enough verifiable facts for '{idea['title']}' ({len(facts.facts)}). Dropped: {dropped}")
    script, t = draft(router, channel, idea, facts)
    writer = t["provider"]
    trail.append({"step": "draft", **t})

    for round_no in range(MAX_REWRITES + 1):
        issues = quality.check_long(script, channel)
        claims = verify.check_claims(router, script, facts, sources, exclude_provider=writer)
        bad = [c for c in claims if c["status"] in ("unsupported", "contradicted")]
        if round_no == MAX_REWRITES or (not issues and not bad):
            break
        targets, notes = [], []
        for i, sc in enumerate(script.scenes, 1):
            if any(c["key"] in sc.claim_keys for c in bad):
                targets.append(i)
        notes += [f"Claim {c['key']} '{c['text']}' is {c['status']}: remove or restate using the fact sheet" for c in bad]
        notes += issues
        if not targets:
            targets = [1, len(script.scenes)] if issues else []
        script, t = rewrite_scenes(router, channel, script, targets, notes, facts, exclude=None)
        trail.append({"step": f"fix_round_{round_no + 1}", **t})

    script, t = voice_edit(router, channel, script, writer)
    trail.append({"step": "voice_edit", **t})
    report, t = critique(router, channel, script, writer)
    trail.append({"step": "critic", **t})
    if report.minimum() < CRITIC_MIN and report.weak_scenes:
        script, t = rewrite_scenes(router, channel, script, report.weak_scenes, report.fixes, facts, exclude=writer)
        trail.append({"step": "critic_fix", **t})
        report, t = critique(router, channel, script, writer)
        trail.append({"step": "critic_recheck", **t})
    script, t = pick_hook(router, script)
    if t:
        trail.append({"step": "hook_pick", **t})

    # last-resort cleanup of banned phrases, then final gates
    script = script.model_copy(update={
        "scenes": [s.model_copy(update={"narration": quality.remove_banned(s.narration)}) for s in script.scenes],
        "hook": quality.remove_banned(script.hook), "cta": quality.remove_banned(script.cta)})
    claims = verify.check_claims(router, script, facts, sources, exclude_provider=writer)
    issues = quality.check_long(script, channel)
    if report.minimum() < CRITIC_MIN:
        issues.append(f"Critic score below {CRITIC_MIN}: {report.model_dump(exclude={'fixes', 'weak_scenes'})}")
    rep = {"critic": report.model_dump(), "issues": issues, "dropped_facts": dropped,
           "claims": {s: sum(1 for c in claims if c["status"] == s) for s in {c["status"] for c in claims}},
           "duration_seconds": script.duration(), "stats": quality.sentence_stats(script.full_text())}
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
    return pkg, problems, res.trail()
