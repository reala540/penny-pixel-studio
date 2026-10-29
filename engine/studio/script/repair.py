"""Targeted repairs a script gets before review. Code fixes what code can decide; the model rewrites only the scenes
that still need it, with the evidence in view. Each repair says what it changed, for the package notes.

- a calculation with a wrong result: recalculated by code, and the number replaced in the claim, the narration and
  the visual of the scenes that state it
- scenes pointing at fact keys (F3) instead of claim keys (C3): linked to the right claims
- an animation showing a number the narrator doesn't say: that label is removed (or the scene becomes a still card)
- the same sentence twice, or the required disclaimer in several places: later copies removed, the disclaimer kept
  once at the end; a scene left nearly empty is merged into its neighbour
- a scene still carrying a statement nobody could support after the rewrites: removed, if the video stays long enough
"""

from __future__ import annotations

import re

from .models import Claim, Scene, Script
from .quality import NUMBER_RE, numbers_in
from .verify import calc_result, is_comparison

DISCLAIMER = re.compile(r"[^.!?]*\b(not (personal|financial) advice|general education|for (education|information)al "
                        r"purposes)\b[^.!?]*[.!?]", re.I)
MIN_SCENE_WORDS = 14


def _fmt_like(original: str, value: float) -> str:
    """`value` written the way `original` was: same decimals, thousands separators when it had them."""
    decimals = len(original.split(".")[1]) if "." in original else 0
    text = f"{value:,.{decimals}f}" if "," in original else f"{value:.{decimals}f}"
    return text


def _replace_number(text: str, old: str, new: str) -> str:
    """Replace the number `old` (as normalised by numbers_in) with `new`, keeping currency signs and units."""
    def sub(m):
        raw = m.group(1)
        norm = raw.replace(",", "")
        if "." in norm:
            norm = norm.rstrip("0").rstrip(".")
        return m.group(0).replace(raw, new, 1) if norm == old else m.group(0)
    return NUMBER_RE.sub(sub, text)


def fix_calculations(script: Script, records: list[dict]) -> tuple[Script, list[str]]:
    """Recalculate each contradicted calculation and put the right number everywhere the wrong one was said."""
    claims = {c.key: c for c in script.claims}
    scenes = list(script.scenes)
    changes = []
    for r in records:
        c = claims.get(r["key"])
        if r["status"] != "contradicted" or not c or c.kind != "calculation" or is_comparison(c.expression):
            continue
        result = calc_result(c.expression)
        if result is None:
            continue
        inputs = numbers_in(c.expression.replace("**", " ** "))
        as_pct = {f"{float(i) * 100:.10f}".rstrip("0").rstrip(".") for i in inputs}  # 0.04 in the sum is "4%"
        years = set(re.findall(r"\b(?:19|20)\d{2}\b", c.text))  # "fiscal 2023" is a date, never the result
        stated = [n for n in numbers_in(c.text) if n not in inputs and n not in as_pct and n not in years]
        if len(stated) != 1:
            continue  # the wrong result can't be told apart from the inputs: the rewrite step handles it
        old = stated[0]
        as_pct = bool(re.search(rf"{re.escape(old)}\s*(%|percent)", c.text.replace(",", ""))) and abs(result) < 50
        value = result * 100 if as_pct else result
        new = _fmt_like(old, round(value, 2 if "." in old else 0))
        if new.replace(",", "") == old:
            continue
        claims[c.key] = c.model_copy(update={"text": _replace_number(c.text, old, new)})
        for i, sc in enumerate(scenes):
            if c.key not in sc.claim_keys:
                continue
            v = sc.visual
            visual = v.model_copy(update={
                "items": [_replace_number(x, old, new) for x in v.items],
                "stat_value": _replace_number(v.stat_value, old, new) if v.stat_value else v.stat_value,
                "headline": _replace_number(v.headline, old, new) if v.headline else v.headline})
            scenes[i] = sc.model_copy(update={"narration": _replace_number(sc.narration, old, new), "visual": visual,
                                              "on_screen_text": _replace_number(sc.on_screen_text, old, new)
                                              if sc.on_screen_text else sc.on_screen_text})
        changes.append(f"Recalculated {c.key}: {c.expression} = {new} (the script said {old})")
    return script.model_copy(update={"claims": list(claims.values()), "scenes": scenes}), changes


def fix_claim_links(script: Script) -> tuple[Script, list[str]]:
    """Scenes that list fact keys (F3) or keys that don't exist: point them at the claims that cite those facts."""
    keys = {c.key for c in script.claims}
    by_fact: dict[str, list[str]] = {}
    for c in script.claims:
        for f in c.fact_refs:
            by_fact.setdefault(f, []).append(c.key)
    scenes, changes = [], []
    for i, sc in enumerate(script.scenes, 1):
        fixed = []
        for k in sc.claim_keys:
            if k in keys:
                fixed.append(k)
            elif k in by_fact:
                fixed += by_fact[k]
        fixed = list(dict.fromkeys(fixed))
        if fixed != sc.claim_keys:
            changes.append(f"Scene {i}: claim links corrected ({', '.join(sc.claim_keys)} → {', '.join(fixed) or 'none'})")
            sc = sc.model_copy(update={"claim_keys": fixed})
        scenes.append(sc)
    return script.model_copy(update={"scenes": scenes}), changes


def fix_animations(script_scenes: list[Scene]) -> tuple[list[Scene], list[str]]:
    """An animation may only show numbers its narrator says: drop the labels that don't match."""
    out, changes = [], []
    for i, sc in enumerate(script_scenes, 1):
        v = sc.visual
        if v.type != "animated":
            out.append(sc)
            continue
        said = numbers_in(sc.narration)
        items = [x for x in v.items if numbers_in(x) <= said]
        stat = v.stat_value if (not v.stat_value or numbers_in(v.stat_value) <= said) else None
        if items == v.items and stat == v.stat_value:
            out.append(sc)
            continue
        if (v.animation == "counter" and not stat) or (v.animation != "counter" and len(items) < 2):
            visual = v.model_copy(update={"type": "title_card", "animation": None, "items": [], "stat_value": None,
                                          "headline": v.headline or v.stat_label or sc.on_screen_text})
            changes.append(f"Scene {i}: animation showed numbers the narrator doesn't say, so it became a still card")
        else:
            visual = v.model_copy(update={"items": items, "stat_value": stat})
            changes.append(f"Scene {i}: removed animation labels with numbers the narrator doesn't say")
        out.append(sc.model_copy(update={"visual": visual}))
    return out, changes


def _sentences(text: str) -> list[str]:
    return [s for s in re.split(r"(?<=[.!?])\s+", text.strip()) if s]


def _key(sentence: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", sentence.lower()).strip()


def remove_repeats(script: Script, money: bool) -> tuple[Script, list[str]]:
    """Later copies of a sentence (7+ words) are removed; a required disclaimer is said once, at the end (the call
    to action), not in several scenes."""
    seen: set[str] = set()
    changes: list[str] = []
    scenes: list[Scene] = []
    disclaimer_in_cta = bool(DISCLAIMER.search(script.cta))
    for i, sc in enumerate(script.scenes, 1):
        kept = []
        for s in _sentences(sc.narration):
            k = _key(s)
            if money and DISCLAIMER.fullmatch(s.strip()) and (disclaimer_in_cta or "disclaimer" in seen):
                changes.append(f"Scene {i}: removed a repeated disclaimer (it is said once at the end)")
                continue
            if len(k.split()) >= 7 and k in seen:
                changes.append(f"Scene {i}: removed a repeated sentence: \"{s[:60]}\"")
                continue
            if money and DISCLAIMER.fullmatch(s.strip()):
                seen.add("disclaimer")
            seen.add(k)
            kept.append(s)
        scenes.append(sc.model_copy(update={"narration": " ".join(kept)}))
    merged, notes = merge_thin(scenes)
    return script.model_copy(update={"scenes": merged}), changes + notes


def merge_thin(scenes: list[Scene]) -> tuple[list[Scene], list[str]]:
    """A scene left with almost no narration joins the scene before it (its claims go with it)."""
    out: list[Scene] = []
    notes = []
    for sc in scenes:
        if len(sc.narration.split()) < MIN_SCENE_WORDS and out:
            prev = out[-1]
            out[-1] = prev.model_copy(update={"narration": f"{prev.narration} {sc.narration}".strip(),
                                              "claim_keys": list(dict.fromkeys(prev.claim_keys + sc.claim_keys))})
            notes.append("A scene left nearly empty was joined to the one before it")
        elif sc.narration.strip():
            out.append(sc)
    return out, notes


def apply_edit_plan(scenes: list[Scene], delete: list[int], merge: list[list[int]]) -> tuple[list[Scene], list[int], list[str]]:
    """Delete and merge scenes as the editor asked (1-based numbers). Returns the new scenes, the positions of merged
    scenes (to rewrite for flow) and what changed. Never removes the first scene or the last one."""
    n = len(scenes)
    protected = {1, n}
    groups = [sorted({x for x in g if 1 <= x <= n}) for g in merge]
    groups = [g for g in groups if len(g) >= 2]
    absorbed = {x for g in groups for x in g[1:]}
    drop = {x for x in delete if 1 <= x <= n and x not in protected} - {g[0] for g in groups}
    out, merged_at, notes = [], [], []
    for i, sc in enumerate(scenes, 1):
        if i in drop or i in absorbed:
            continue
        group = next((g for g in groups if g[0] == i), None)
        if group:
            parts = [scenes[j - 1] for j in group if j not in drop]
            sc = sc.model_copy(update={"narration": " ".join(p.narration for p in parts),
                                       "claim_keys": list(dict.fromkeys(k for p in parts for k in p.claim_keys))})
            merged_at.append(len(out) + 1)
            notes.append(f"Merged scenes {', '.join(map(str, group))}")
        out.append(sc)
    if drop:
        notes.append(f"Removed scenes {', '.join(map(str, sorted(drop)))} (repetition or off-topic)")
    return out, merged_at, notes


def drop_unsupported_scenes(script: Script, records: list[dict], min_seconds: float,
                            speed: float = 1.0) -> tuple[Script, list[str], list[dict]]:
    """Last resort after the rewrites: remove scenes whose statements still can't be backed, if the video stays at
    least `min_seconds` long. Returns the script, what changed, and the claims that remain unresolved."""
    bad = {r["key"] for r in records if r["status"] in BAD}
    if not bad:
        return script, [], []
    scenes = list(script.scenes)
    removed = []
    for i in range(len(scenes) - 2, 0, -1):  # never the first or last scene
        if not bad & set(scenes[i].claim_keys):
            continue
        trial = scenes[:i] + scenes[i + 1:]
        if sum(est(s.narration, speed) for s in trial) >= min_seconds:
            removed.append(i + 1)
            scenes = trial
    still = {k for s in scenes for k in s.claim_keys} & bad
    claims = prune_claims(scenes, script.claims)
    notes = [f"Removed scene {n}: its statement couldn't be backed by the sources" for n in sorted(removed)]
    return (script.model_copy(update={"scenes": scenes, "claims": claims}), notes,
            [r for r in records if r["key"] in still])


def prune_claims(scenes: list[Scene], claims: list[Claim]) -> list[Claim]:
    """Only the claims some scene still makes."""
    used = {k for s in scenes for k in s.claim_keys}
    return [c for c in claims if c.key in used]


def est(text: str, speed: float = 1.0) -> float:
    from .models import est_seconds

    return est_seconds(text, speed)


BAD = ("unsupported", "contradicted", "stale")
