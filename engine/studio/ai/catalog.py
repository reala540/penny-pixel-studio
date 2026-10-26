"""Keeps configured model names in step with what each free provider actually serves today.

Providers retire and rename models often. `refresh` asks every provider for its current model list (the
OpenAI-compatible `/models` endpoint) and, for each configured model that has disappeared, picks the newest
model of the same family. The result is stored in settings['model_catalog'] and the router follows it.
"""

from __future__ import annotations

import os
import re
from typing import Any

import httpx

NOT_CHAT = re.compile(r"embed|tts|whisper|audio|image|imagen|vision-only|guard|moderation|rerank|transcrib|live|veo|aqa",
                      re.I)


def family(model_id: str) -> str:
    """'gemini-2.5-pro' -> 'gemini|pro', 'z-ai/glm-5.2' -> 'z-ai/glm', 'kimi-k3' -> 'kimi'."""
    base = model_id.split(":")[0]
    head, _, name = base.rpartition("/")
    sizes = ("pro", "flash", "lite", "mini", "nano", "large", "medium", "small", "ultra", "super", "instruct", "it")
    tokens = [t for t in re.split(r"[-_.]", name.lower()) if t]
    stem_words: list[str] = []
    for t in tokens:  # the name before the first version number or size word: 'gpt-oss-20b' -> 'gpt-oss'
        if re.fullmatch(r"v?\d+[a-z]?\d*|k\d+", t) or t in sizes:
            break
        stem_words.append(t)
    stem = "-".join(stem_words) or (tokens[0] if tokens else name.lower())
    size = next((t for t in tokens if t in sizes), "")
    return f"{head + '/' if head else ''}{stem}|{size}"


def _version(model_id: str) -> tuple:
    nums = [int(n) for n in re.findall(r"\d+", model_id.split("/")[-1])]
    stable = 0 if re.search(r"preview|exp|beta|alpha", model_id, re.I) else 1
    return (stable, *nums)


def _plain(model_id: str) -> str:
    """'glm-4.7:cloud' and 'glm-4.7-cloud' are the same model as 'glm-4.7' (the hosted name differs by suffix)."""
    return re.sub(r"(?::|-)cloud$", "", model_id.removeprefix("models/").lower())


def pick_substitute(missing: str, available: list[str], free_only: bool = False) -> str | None:
    same_model = [m for m in available if _plain(m) == _plain(missing)]
    if same_model:  # the same model under its listed name: never swap it for a different (maybe paid) one
        return same_model[0]
    fam = family(missing)
    pool = [m for m in available if not NOT_CHAT.search(m) and (not free_only or m.endswith(":free"))]
    same = [m for m in pool if family(m) == fam]
    if not same:  # same maker and model line, any size
        same = [m for m in pool if family(m).split("|")[0] == fam.split("|")[0]]
    return max(same, key=_version) if same else None


def list_models(client: httpx.Client, base_url: str, key: str | None) -> list[str] | None:
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    try:
        r = client.get(f"{base_url.rstrip('/')}/models", headers=headers, timeout=20)
    except httpx.HTTPError:
        return None
    if r.status_code != 200:
        return None
    try:
        data = r.json()
    except ValueError:
        return None
    items = data.get("data") if isinstance(data, dict) else data
    ids = []
    for it in items or []:
        mid = it.get("id") if isinstance(it, dict) else it
        if isinstance(mid, str):
            ids.append(mid.removeprefix("models/"))
    return ids or None


def refresh(providers_cfg: dict, client: httpx.Client | None = None) -> dict[str, Any]:
    """Return {provider: {"listed": bool, "missing": {configured_id: substitute_or_None}}}."""
    client = client or httpx.Client(timeout=20, follow_redirects=True)
    out: dict[str, Any] = {}
    for name, p in (providers_cfg.get("providers") or {}).items():
        key = os.environ.get(p.get("key_env") or "") or None
        base = p.get("base_url", "")
        if (not key and not p.get("key_optional")) or "${" in base:
            continue
        ids = list_models(client, base, key)
        if ids is None:
            out[name] = {"listed": False, "missing": {}}
            continue
        missing = {}
        for m in p.get("models", []):
            if m.get("kind", "chat") != "chat" or m["id"] in ids:
                continue
            missing[m["id"]] = pick_substitute(m["id"], ids, free_only=m["id"].endswith(":free"))
        out[name] = {"listed": True, "missing": missing, "ids": sorted(ids)[:400]}  # what the provider serves today
    return out


def effective_model(catalog: dict, provider: str, model_id: str) -> str | None:
    """The model to call for a configured id: itself, its substitute, or None if it's gone with no substitute."""
    missing = (catalog.get(provider) or {}).get("missing") or {}
    if model_id not in missing:
        return model_id
    return missing[model_id]


_SUGGESTED = re.compile(r"(?:update your code to use|use instead|has been replaced by|migrate to)\s+(?:models/)?([A-Za-z0-9._:/-]+[A-Za-z0-9])",
                        re.I)


def suggested_replacement(error_text: str) -> str | None:
    """Providers often name the replacement when they retire a model; use it."""
    m = _SUGGESTED.search(error_text or "")
    return m.group(1) if m else None
