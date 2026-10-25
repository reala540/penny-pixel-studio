"""Deterministic quality gates. These never call an AI: they are the rules the AI must satisfy."""

from __future__ import annotations

import re
from collections import Counter

from .. import config
from .models import Script, ShortScript, est_seconds

MIN_LONG_SECONDS = 480  # long videos run 8-14 minutes (tests lower this to keep renders quick)

NUMBER_RE = re.compile(r"(?<![\w.])(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)\s*(%|percent|k|m|bn|billion|million|thousand)?",
                       re.IGNORECASE)


def numbers_in(text: str) -> set[str]:
    """Normalised numbers mentioned in text: '1,200' -> '1200', '4.5%' -> '4.5'."""
    out = set()
    for m in NUMBER_RE.finditer(text):
        n = m.group(1).replace(",", "")
        if "." in n:
            n = n.rstrip("0").rstrip(".")
        out.add(n)
    return out


def banned_hits(text: str) -> list[str]:
    low = text.lower()
    return [p for p in config.brand().get("banned_phrases", []) if p.lower() in low]


def remove_banned(text: str) -> str:
    """Last-resort cleanup for a few phrases (the voice editor should already have removed them)."""
    replacements = {"let's dive in": "here's the plan", "it's important to note that": "", "in conclusion,": "so,",
                    "game-changer": "big shift", "game changer": "big shift", "seamlessly": "smoothly",
                    "cutting-edge": "new", "delve into": "look at", "delve": "dig"}
    for k, v in replacements.items():
        text = re.sub(re.escape(k), v, text, flags=re.IGNORECASE)
    return re.sub(r"\s{2,}", " ", text).strip()


def sentence_stats(text: str) -> dict:
    sentences = [s for s in re.split(r"(?<=[.!?])\s+", text.strip()) if s]
    lengths = [len(s.split()) for s in sentences]
    starts = Counter(" ".join(s.split()[:2]).lower() for s in sentences)
    limit = max(4, int(len(sentences) * 0.08) + 1)  # a few repeats are natural in a long script
    repeated = [k for k, v in starts.items() if v >= limit]
    return {"sentences": len(sentences), "avg_words": round(sum(lengths) / max(len(lengths), 1), 1),
            "max_words": max(lengths or [0]), "repeated_openers": repeated}


# The studio researches from sources; it doesn't use tools hands-on, so the script must never say it did.
INVENTED_TEST = re.compile(r"\b(I|we|I've|we've|I have|we have)\s+(personally\s+)?(tried|tested|been testing|been using|"
                           r"put .{0,20} to the test|ran .{0,20} through)\b", re.IGNORECASE)


def invented_tests(text: str) -> list[str]:
    return [m.group(0) for m in INVENTED_TEST.finditer(text)]


def drop_invented_tests(text: str) -> str:
    """Remove whole sentences that claim a hands-on test (post texts are short; a sentence is the safe unit)."""
    parts = re.split(r"(?<=[.!?])\s+", text)
    return " ".join(p for p in parts if not INVENTED_TEST.search(p)).strip()


# Money rules that only apply in one country: a video built on them says which country in its title.
COUNTRY_TERMS = {
    "US": r"401\(?k\)?|\bIRAs?\b|\bRoth\b|\bFICO\b|\bIRS\b|\bHSAs?\b|\b529 plans?\b|Social Security|\bFDIC\b|\bW-2\b|\b1099\b|Medicare",
    "UK": r"\bISAs?\b|\bHMRC\b|\bLISA\b|National Insurance|State Pension",
    "Canada": r"\bRRSPs?\b|\bTFSAs?\b|\bFHSA\b|\bCRA\b|\bCPP\b",
    "Australia": r"superannuation|\bATO\b|\bHECS\b|Centrelink",
}
COUNTRY_MARK = {"US": r"\b(US|U\.S\.|USA|America|Americans?)\b", "UK": r"\b(UK|U\.K\.|Britain|British)\b",
                "Canada": r"\bCanad(a|ian)\b", "Australia": r"\bAustralian?\b"}


def main_country(text: str) -> str | None:
    """The country whose money rules a script relies on most, if any."""
    hits = {c: len(re.findall(p, text, re.IGNORECASE if c == "Australia" else 0)) for c, p in COUNTRY_TERMS.items()}
    best = max(hits, key=hits.get)
    return best if hits[best] else None


def with_country(title: str, country: str | None, limit: int = 100) -> str:
    if not country or re.search(COUNTRY_MARK[country], title):
        return title
    tagged = f"{title.rstrip()} ({country})"
    return tagged if len(tagged) <= limit else title


def repeated_sentences(text: str, min_words: int = 7) -> list[str]:
    """Sentences (7+ words) that appear more than once: padding, not content."""
    seen = Counter(re.sub(r"[^a-z0-9 ]", "", s.lower()).strip() for s in re.split(r"(?<=[.!?])\s+", text))
    return [s for s, n in seen.items() if n > 1 and len(s.split()) >= min_words]


def check_long(script: Script, channel: str) -> list[str]:
    issues: list[str] = []
    cfg = config.services()["render"]
    ch = config.brand()["channels"][channel]
    speed = float(ch["voice_profile"].get("tts_speed", 1.0))
    dur = script.duration(speed)
    if not 6 <= len(script.scenes) <= 40:
        issues.append(f"Needs 6-40 scenes, has {len(script.scenes)}")
    if dur < MIN_LONG_SECONDS:
        issues.append(f"Too short: about {dur / 60:.1f} min (aim for {MIN_LONG_SECONDS // 60}-{cfg['max_long_minutes']} min)")
    if dur > cfg["max_long_minutes"] * 60:
        issues.append(f"Too long: about {dur / 60:.1f} min (max {cfg['max_long_minutes']})")
    claimed = invented_tests(script.full_text() + " " + script.hook + " " + script.title)
    if claimed:
        issues.append(f"Claims a hands-on test that didn't happen: \"{claimed[0]}\" (say what the sources found)")
    padding = repeated_sentences(script.full_text())
    if padding:
        issues.append(f"Repeats itself to fill time: \"{padding[0][:80]}\"" + (f" and {len(padding) - 1} more" if len(padding) > 1 else ""))
    if len(script.hook.split()) > 45:
        issues.append("Hook is longer than 45 words")
    if not script.cta.strip():
        issues.append("Missing call to action")
    issues += _common(script.full_text() + " " + script.hook + " " + script.cta, channel)
    for i, sc in enumerate(script.scenes, 1):
        if est_seconds(sc.narration, speed) > 45:
            issues.append(f"Scene {i} is too long for one visual (split it)")
        if sc.visual.type == "chart" and not sc.visual.chart:
            issues.append(f"Scene {i} says chart but has no chart data")
    claim_keys = {c.key for c in script.claims}
    for i, sc in enumerate(script.scenes, 1):
        unknown = [k for k in sc.claim_keys if k not in claim_keys]
        if unknown:
            issues.append(f"Scene {i} references unknown claims {unknown}")
    for i, sc in enumerate(script.scenes, 1):
        nums = numbers_in(sc.narration) - {"1", "2", "3", "4", "5", "10"}
        if nums and not sc.claim_keys:
            issues.append(f"Scene {i} states numbers {sorted(nums)} without a claim/source")
    return issues


def check_short(short: ShortScript, channel: str) -> list[str]:
    issues: list[str] = []
    speed = float(config.brand()["channels"][channel]["voice_profile"].get("tts_speed", 1.0))
    dur = sum(est_seconds(s.narration, speed) for s in short.scenes) + est_seconds(short.hook, speed)
    max_s = config.services()["render"]["max_short_seconds"]
    if dur > max_s:
        issues.append(f"Short too long: ~{dur:.0f}s (max {max_s})")
    if dur < 20:
        issues.append(f"Short too thin: ~{dur:.0f}s")
    if not 2 <= len(short.scenes) <= 8:
        issues.append("Short needs 2-8 scenes")
    claimed = invented_tests(" ".join(s.narration for s in short.scenes) + " " + short.hook + " " + short.title)
    if claimed:
        issues.append(f"Claims a hands-on test that didn't happen: \"{claimed[0]}\"")
    issues += _common(" ".join(s.narration for s in short.scenes) + " " + short.hook + " " + short.caption, channel,
                      require_disclaimer=False)
    return issues


def _common(text: str, channel: str, require_disclaimer: bool = True) -> list[str]:
    issues = []
    hits = banned_hits(text)
    if hits:
        issues.append(f"Generic phrases: {', '.join(hits)}")
    stats = sentence_stats(text)
    if stats["avg_words"] > 22:
        issues.append(f"Sentences too long on average ({stats['avg_words']} words)")
    if stats["repeated_openers"]:
        issues.append(f"Repetitive sentence openings: {stats['repeated_openers']}")
    if channel == "money":
        low = text.lower()
        if re.search(r"guarantee(d)? (return|profit|income)|will (definitely|certainly) (rise|grow|double)", low):
            issues.append("Promises returns or predicts prices")
        if require_disclaimer and "not personal" not in low and "not financial advice" not in low and "general education" not in low:
            issues.append("Money script must say it is general education, not personal advice")
    return issues
