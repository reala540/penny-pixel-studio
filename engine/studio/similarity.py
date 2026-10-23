"""Repetition detection: free embeddings when available, local TF-IDF cosine otherwise."""

from __future__ import annotations

import math
import re
from collections import Counter

STOP = set("""a an the and or but if then of to in on for with by at from as is are was were be been being this
that these those it its you your we our they their i my me he she him her them how what why when where which who
will can could should would do does did not no yes so than too very just about into over after before more most
""".split())


def tokens(text: str) -> list[str]:
    words = [w for w in re.findall(r"[a-z0-9]+", text.lower()) if w not in STOP and len(w) > 1]
    return words + [f"{a}_{b}" for a, b in zip(words, words[1:])]


def _tfidf(docs: list[list[str]]) -> list[dict[str, float]]:
    df = Counter(t for d in docs for t in set(d))
    n = len(docs)
    out = []
    for d in docs:
        tf = Counter(d)
        vec = {t: (c / max(len(d), 1)) * (math.log((1 + n) / (1 + df[t])) + 1) for t, c in tf.items()}
        out.append(vec)
    return out


def _cos(a: dict[str, float], b: dict[str, float]) -> float:
    dot = sum(v * b.get(k, 0.0) for k, v in a.items())
    na = math.sqrt(sum(v * v for v in a.values()))
    nb = math.sqrt(sum(v * v for v in b.values()))
    return dot / (na * nb) if na and nb else 0.0


def _cos_dense(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


# Embedding cosine and TF-IDF cosine live on different scales, so each has its own threshold.
REPEAT_THRESHOLD = {"embeddings": 0.82, "lexical": 0.45}


def max_similarity(candidate: str, history: list[str], router=None) -> tuple[float, int | None, str]:
    """Highest similarity between `candidate` and any history text: (score, index, method)."""
    if not history:
        return 0.0, None, "lexical"
    if router is not None:
        vecs = router.embed([candidate] + history)
        if vecs:
            scores = [_cos_dense(vecs[0], v) for v in vecs[1:]]
            best = max(range(len(scores)), key=scores.__getitem__)
            return scores[best], best, "embeddings"
    vecs = _tfidf([tokens(candidate)] + [tokens(h) for h in history])
    scores = [_cos(vecs[0], v) for v in vecs[1:]]
    best = max(range(len(scores)), key=scores.__getitem__)
    return scores[best], best, "lexical"


def is_repeat(score: float, method: str) -> bool:
    return score >= REPEAT_THRESHOLD[method]


def lexical_similarity(a: str, b: str) -> float:
    vecs = _tfidf([tokens(a), tokens(b)])
    return _cos(vecs[0], vecs[1])
