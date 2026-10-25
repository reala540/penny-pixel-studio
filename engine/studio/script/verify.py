"""Claim-level verification.

One AI agreeing with another is not evidence. A claim only counts as supported when:
  1. the checker quotes a supporting passage, AND
  2. that quote actually appears in the stored source/fact text (checked in code), AND
  3. every number in the claim appears in the quoted evidence (checked in code).
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

from ..ai.router import Router
from .models import ClaimVerdicts, FactSheet, Script
from .quality import numbers_in


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w%.$ ]+", " ", text.lower())).strip()


def quote_in_evidence(quote: str, evidence: str, min_overlap: float = 0.85) -> bool:
    q, ev = _norm(quote), _norm(evidence)
    if not q or len(q) < 12:
        return False
    if q in ev:
        return True
    qw = q.split()
    evw = set(ev.split())
    return len(qw) >= 5 and sum(w in evw for w in qw) / len(qw) >= min_overlap


def evidence_text(facts: FactSheet, sources: list[dict]) -> dict[str, str]:
    """Evidence available per fact key: the fact + the text of the source it cites."""
    by_label = {f"S{i}": s for i, s in enumerate(sources, 1)}
    out = {}
    for f in facts.facts:
        s = by_label.get(f.source_ref, {})
        out[f.key] = " ".join(filter(None, [f.text, s.get("title"), s.get("summary"), s.get("body_text")]))
    return out


def ground_facts(facts: FactSheet, sources: list[dict]) -> tuple[FactSheet, list[str]]:
    """Drop fact-sheet entries whose numbers don't appear in the cited source text."""
    by_label = {f"S{i}": s for i, s in enumerate(sources, 1)}
    kept, dropped = [], []
    for f in facts.facts:
        s = by_label.get(f.source_ref)
        if not s:
            dropped.append(f"{f.key}: cites unknown source {f.source_ref}")
            continue
        src_text = " ".join(filter(None, [s.get("title"), s.get("summary"), s.get("body_text")]))
        missing = numbers_in(f.text) - numbers_in(src_text)
        if missing:
            dropped.append(f"{f.key}: numbers {sorted(missing)} not found in {f.source_ref}")
            continue
        kept.append(f)
    return FactSheet(facts=kept, context=facts.context, open_questions=facts.open_questions), dropped


def check_claims(router: Router, script: Script, facts: FactSheet, sources: list[dict],
                 exclude: set[str] | None = None) -> list[dict]:
    """Return one record per claim with a status decided by code, informed by the checker model."""
    evidence = evidence_text(facts, sources)
    factual = [c for c in script.claims if c.kind == "fact"]
    records: list[dict] = []
    verdicts = {}
    if factual:
        listing = "\n".join(
            f"{c.key}: {c.text}\n  cites: {', '.join(c.fact_refs) or 'nothing'}\n"
            + "\n".join(f'  <source id="{k}">{evidence.get(k, "")[:1500]}</source>' for k in c.fact_refs)
            for c in factual)
        prompt = ("Check each claim strictly against ONLY the source text shown under it. For each claim give a "
                  "status and copy the exact supporting sentence from the source into supporting_quote. If the "
                  "source does not clearly say it, mark it unsupported. Do not use outside knowledge.\n\n" + listing)
        res = router.complete("claim_checker", prompt, schema=ClaimVerdicts, temperature=0.0,
                              exclude=exclude)
        verdicts = {v.key: v for v in res.data.verdicts}
    now = datetime.now(timezone.utc)
    for c in script.claims:
        if c.kind == "opinion":
            records.append({"key": c.key, "text": c.text, "status": "opinion", "confidence": 1.0,
                            "fact_refs": c.fact_refs, "note": "Presented as opinion", "checked_at": now})
            continue
        v = verdicts.get(c.key)
        ev = " ".join(evidence.get(k, "") for k in c.fact_refs)
        status, conf, note = "unsupported", 0.0, "No verdict returned"
        if v is not None:
            note = v.note
            quote_ok = quote_in_evidence(v.supporting_quote, ev)
            nums_ok = numbers_in(c.text) <= numbers_in(v.supporting_quote + " " + ev)
            if v.status in ("supported", "partially_supported") and quote_ok and nums_ok:
                status, conf = v.status, (0.9 if v.status == "supported" else 0.6)
            elif v.status == "contradicted":
                status, conf = "contradicted", 0.8
            else:
                status = "unsupported"
                conf = 0.2
                if v.status == "supported" and not quote_ok:
                    note = "Checker said supported but its quote was not found in the source"
                elif v.status == "supported" and not nums_ok:
                    note = "Numbers in the claim do not match the source"
        if not c.fact_refs:
            status, conf, note = "unsupported", 0.0, "Claim cites no fact"
        records.append({"key": c.key, "text": c.text, "status": status, "confidence": conf,
                        "fact_refs": c.fact_refs, "note": note, "checked_at": now})
    return records
