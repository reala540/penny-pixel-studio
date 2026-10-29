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
_CMP = {ast.Lt: operator.lt, ast.LtE: operator.le, ast.Gt: operator.gt, ast.GtE: operator.ge}
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
        if isinstance(n, ast.Compare) and len(n.ops) == 1 and type(n.ops[0]) in _CMP:
            return 1.0 if _CMP[type(n.ops[0])](ev(n.left), ev(n.comparators[0])) else 0.0
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
    expression = arithmetic_only(expression)
    text = digits_for_words(text)
    if not re.search(r"[-+*/^<>%]", expression.replace("**", "*")):
        return "unsupported", 0.0, "Not a calculation (no arithmetic): cite the fact the number comes from"
    try:
        result = safe_eval(expression)
    except (ValueError, SyntaxError, ZeroDivisionError, OverflowError) as exc:
        return "unsupported", 0.0, f"Couldn't recalculate: {exc}"[:200]
    stated = numbers_in(text)
    inputs = numbers_in(expression.replace("**", " ** "))
    known = stated | fact_numbers | PLAIN_CONSTANTS | scaled_numbers(text)

    def as_percent(n: str) -> str:  # 0.05 in the arithmetic is the "5%" the claim or a fact states
        p = f"{float(n) * 100:.10f}".rstrip("0").rstrip(".")
        return p

    unknown = sorted(n for n in inputs - known if as_percent(n) not in known)
    if unknown:
        return "unsupported", 0.0, f"Uses numbers with no source or stated assumption: {unknown}"
    if is_comparison(expression):  # "lower than", "more than": code checks the comparison itself
        if result == 1.0:
            return "supported", 0.95, f"Comparison checked by code: {expression} is true"
        return "contradicted", 0.9, f"Comparison is false: {expression}"
    for n in stated:
        v = float(n)
        if abs(v - result) <= max(0.01 * abs(result), 0.51) or (result and abs(v - result * 100) <= max(abs(result), 0.51)):
            return "supported", 0.95, f"Recalculated by code: {expression} = {result:,.2f}"
    results = [n for n in stated if n not in inputs and as_percent(n) not in {as_percent(i) for i in inputs}
               and n not in {as_percent(i) for i in inputs}]
    if not results:
        return "unsupported", 0.0, f"The result isn't stated: {expression} = {result:,.2f}; say the number or drop the sum"
    return "contradicted", 0.9, f"Math is wrong: {expression} = {result:,.2f}, not what the script says"


SCALE = {"k": 1e3, "thousand": 1e3, "m": 1e6, "million": 1e6, "bn": 1e9, "billion": 1e9}


def scaled_numbers(text: str) -> set[str]:
    """'$1 million' is also 1000000 and '$37.5 billion' 37500000000, as a sum would write them."""
    from .quality import NUMBER_RE

    out = set()
    for m in NUMBER_RE.finditer(text):
        unit = (m.group(2) or "").lower()
        if unit == "m" and text[m.end():m.end() + 6].lower().startswith("illion"):
            unit = "million"
        if unit in SCALE:
            v = float(m.group(1).replace(",", "")) * SCALE[unit]
            out.add(f"{v:.6f}".rstrip("0").rstrip("."))
    return out


NUMBER_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
                "ten": 10, "eleven": 11, "twelve": 12, "twenty": 20, "thirty": 30, "fifty": 50, "hundred": 100}


def digits_for_words(text: str) -> str:
    """'six months' -> '6 months', so a number said in words is checked like one written in digits."""
    return re.sub(r"\b(" + "|".join(NUMBER_WORDS) + r")\b", lambda m: str(NUMBER_WORDS[m.group(1).lower()]), text,
                  flags=re.I)


def arithmetic_only(expression: str) -> str:
    """Writers often give 'result = sum' or 'sum = result': keep the side with the arithmetic."""
    if "==" in expression or not re.search(r"(?<![<>!=])=(?!=)", expression):
        return expression.strip()
    sides = [x.strip() for x in re.split(r"(?<![<>!=])=(?!=)", expression) if x.strip()]
    with_ops = [x for x in sides if re.search(r"[-+*/^]", x.lstrip("-"))]
    return (with_ops or sides)[0]


def is_comparison(expression: str) -> bool:
    return bool(re.search(r"[<>]", expression))


def calc_result(expression: str) -> float | None:
    try:
        return safe_eval(expression)
    except (ValueError, SyntaxError, ZeroDivisionError, OverflowError):
        return None


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


FORECAST_WORDS = re.compile(r"\b(expect\w*|forecast\w*|predict\w*|project\w*|estimat\w*|could|may|might|likely|"
                            r"plan\w*|aim\w*|target\w*|outlook|anticipat\w*|will)\b", re.I)
YEAR = re.compile(r"\b(19|20)\d{2}\b|\b(last|this|next) (year|month|quarter|spring|summer|autumn|fall|winter)\b", re.I)
BATCH = 8  # claims per checker call, so each claim's evidence fits a free model's context


def fact_index(script: Script, facts: FactSheet | None) -> dict:
    """The facts a script version was written against: saved with it, else the fact sheet passed in."""
    from .models import Fact

    listed = list(script.facts) or (list(facts.facts) if facts else [])
    return {f.key: (f if isinstance(f, Fact) else Fact.model_validate(f)) for f in listed}


def check_claims(router: Router, script: Script, facts: FactSheet, sources: list[dict],
                 exclude: set[str] | None = None) -> list[dict]:
    """One record per claim with a status decided by code, informed by the checker model. The checker sees, for
    each cited fact, its passage, its source's publication date and the parts of the full article that match the
    claim, so a fact stated anywhere in a long article (or only by its date) can be confirmed."""
    from . import evidence

    index = fact_index(script, facts)
    by_id = {str(s.get("id")): s for s in sources if s.get("id")}
    by_label = {f"S{i}": s for i, s in enumerate(sources, 1)}
    for f in index.values():  # facts from before evidence links existed: find their source by label
        if not f.source_id and f.source_ref in by_label:
            by_id.setdefault(f"label:{f.source_ref}", by_label[f.source_ref])
            index[f.key] = f.model_copy(update={"source_id": f"label:{f.source_ref}",
                                                "published": f.published or evidence._date(by_label[f.source_ref])})
    ev = {c.key: "\n".join(evidence.evidence_for(index[k], by_id, c.text) for k in c.fact_refs if k in index)
          for c in script.claims}
    factual = [c for c in script.claims if c.kind == "fact" and c.fact_refs]
    verdicts = {}
    for i in range(0, len(factual), BATCH):
        part = factual[i:i + BATCH]
        listing = "\n\n".join(f"{c.key}: {c.text}\n  cites: {', '.join(c.fact_refs)}\n"
                               f'  <evidence id="{c.key}">\n{ev[c.key][:4000]}\n  </evidence>' for c in part)
        prompt = ("Check each claim strictly against ONLY the evidence shown under it (the fact, its passage, the "
                  "source's publication date and more text from the same article). A year or date given as the "
                  "source's publication date or data period counts as stated. supported = the evidence says it; "
                  "partially_supported = the evidence says most of it but the claim is a little broader or less "
                  "exact; unsupported = the evidence doesn't say it; contradicted = the evidence says otherwise. "
                  "Copy the exact supporting sentence from the evidence into supporting_quote. Do not use outside "
                  "knowledge.\n\n" + listing)
        res = router.complete("claim_checker", prompt, schema=ClaimVerdicts, temperature=0.0, exclude=exclude)
        verdicts.update({v.key: v for v in res.data.verdicts})
    now = datetime.now(timezone.utc)
    fact_numbers = set().union(*[numbers_in(f.text) for f in index.values()]) if index else set()
    records: list[dict] = []
    for c in script.claims:
        cited = [index[k] for k in c.fact_refs if k in index]

        def rec(status, conf, note):
            records.append({"key": c.key, "text": c.text, "status": status, "confidence": conf,
                            "fact_refs": c.fact_refs, "note": note, "checked_at": now, "kind": c.kind})

        if c.kind == "calculation":
            rec(*check_calculation(c.text, c.expression, fact_numbers | evidence.date_numbers(cited)))
            continue
        if c.kind == "opinion":
            rec("opinion", 1.0, "Presented as opinion")
            continue
        if c.kind == "principle":
            if numbers_in(c.text) or not c.text.strip():
                rec("unsupported", 0.0, "A general principle can't state numbers: cite the fact behind them")
            else:
                rec("general", 0.8, "General principle (no specific figure, name or date)")
            continue
        if not c.fact_refs or not cited:
            rec("unsupported", 0.0, "Claim cites no fact" if not c.fact_refs else "Claim cites facts that don't exist")
            continue
        v = verdicts.get(c.key)
        evidence_text_all = ev.get(c.key, "")
        status, conf, note = "unsupported", 0.0, "No verdict returned"
        if v is not None:
            note = v.note
            quote_ok = quote_in_evidence(v.supporting_quote, evidence_text_all)
            nums_ok = numbers_in(c.text) <= (numbers_in(v.supporting_quote + " " + evidence_text_all)
                                             | evidence.date_numbers(cited))
            if v.status in ("supported", "partially_supported") and quote_ok and nums_ok:
                status, conf = v.status, (0.9 if v.status == "supported" else 0.6)
            elif v.status == "contradicted" and quote_ok:
                status, conf = "contradicted", 0.8
            else:
                status, conf = "unsupported", 0.2
                if v.status == "contradicted":
                    note = f"Checker said contradicted but its quote was not found in the evidence. {v.note}".strip()
                elif v.status in ("supported", "partially_supported") and not quote_ok:
                    note = "Checker said supported but its quote was not found in the evidence"
                elif v.status in ("supported", "partially_supported") and not nums_ok:
                    note = "Numbers in the claim do not match the evidence"
        if status in ("supported", "partially_supported"):
            if any(f.time_kind == "historical" for f in cited) and not YEAR.search(c.text):
                status, conf, note = "stale", 0.3, ("An old figure said as if it were current: say when it applied "
                                                    f"(the source is from {cited[0].published or 'an earlier date'})")
            elif any(f.time_kind == "forecast" for f in cited) and not FORECAST_WORDS.search(c.text):
                status, conf, note = "unsupported", 0.3, "A forecast stated as a fact: say who expects it"
        rec(status, conf, note)
    return records
