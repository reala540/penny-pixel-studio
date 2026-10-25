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

import ast
import operator

# Numbers a calculation may use without a source: units of time and simple counts.
PLAIN_CONSTANTS = {"0", "1", "2", "3", "4", "5", "6", "7", "8", "9", "10", "12", "24", "52", "60", "100", "365", "1000"}
_OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv,
        ast.Pow: operator.pow, ast.Mod: operator.mod, ast.USub: operator.neg, ast.UAdd: operator.pos}


def safe_eval(expression: str) -> float:
    """Evaluate plain arithmetic (numbers, + - * / ** %, brackets, round) — nothing else can run."""
    def ev(n):
        if isinstance(n, ast.Expression):
            return ev(n.body)
        if isinstance(n, ast.Constant) and isinstance(n.value, (int, float)) and not isinstance(n.value, bool):
            return float(n.value)
        if isinstance(n, ast.BinOp) and type(n.op) in _OPS:
            a, b = ev(n.left), ev(n.right)
            if isinstance(n.op, ast.Pow) and (abs(b) > 1000 or abs(a) > 1e6):
                raise ValueError("exponent too large")
            return _OPS[type(n.op)](a, b)
        if isinstance(n, ast.UnaryOp) and type(n.op) in _OPS:
            return _OPS[type(n.op)](ev(n.operand))
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "round" and not n.keywords:
            args = [ev(a) for a in n.args]
            return float(round(args[0], int(args[1]) if len(args) > 1 else 0))
        raise ValueError(f"not plain arithmetic: {ast.dump(n)[:60]}")
    expr = expression.replace("^", "**").replace("×", "*").replace(",", "")
    return ev(ast.parse(expr, mode="eval"))


def check_calculation(text: str, expression: str, fact_numbers: set[str]) -> tuple[str, float, str]:
    """Recalculate a number the script worked out. Code decides, not a model: the result must match a number the
    claim states (within 1%, or rounding to the nearest whole unit) and every input must come from the fact sheet,
    from the claim's own stated assumptions, or be a plain constant like 12 months."""
    if not expression.strip():
        return "unsupported", 0.0, "Calculation without its arithmetic"
    try:
        result = safe_eval(expression)
    except (ValueError, SyntaxError, ZeroDivisionError, OverflowError) as exc:
        return "unsupported", 0.0, f"Couldn't recalculate: {exc}"[:200]
    stated = numbers_in(text)
    inputs = numbers_in(expression.replace("**", " ** "))
    known = stated | fact_numbers | PLAIN_CONSTANTS

    def as_percent(n: str) -> str:  # 0.05 in the arithmetic is the "5%" the claim or a fact states
        p = f"{float(n) * 100:.10f}".rstrip("0").rstrip(".")
        return p

    unknown = sorted(n for n in inputs - known if as_percent(n) not in known)
    if unknown:
        return "unsupported", 0.0, f"Uses numbers with no source or stated assumption: {unknown}"
    for n in stated:
        v = float(n)
        if abs(v - result) <= max(0.01 * abs(result), 0.51) or (result and abs(v - result * 100) <= max(abs(result), 0.51)):
            return "supported", 0.95, f"Recalculated by code: {expression} = {result:,.2f}"
    return "contradicted", 0.9, f"Math is wrong: {expression} = {result:,.2f}, not what the script says"


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
    fact_numbers = set().union(*[numbers_in(f.text) for f in facts.facts]) if facts.facts else set()
    for c in script.claims:
        if c.kind == "calculation":
            status, conf, note = check_calculation(c.text, c.expression, fact_numbers)
            records.append({"key": c.key, "text": c.text, "status": status, "confidence": conf,
                            "fact_refs": c.fact_refs, "note": note, "checked_at": now})
            continue
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
