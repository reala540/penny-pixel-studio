"""Scripted stand-ins for external services. They exercise the real Router parsing/validation code
by returning JSON text exactly like an OpenAI-compatible provider would."""

from __future__ import annotations

import json
import re

import httpx

from studio.ai.router import AIResult, Candidate, Router
from studio.ai.usage import MemoryUsageStore

SENTENCES = [
    "Picture a normal Tuesday and a decision that quietly costs you every month.",
    "Most people never check this, and that is exactly why it works against them.",
    "The easy option feels free, but the bill arrives later with interest.",
    "A careful option takes ten quiet minutes and saves you a lot of stress.",
    "Write the number down before you decide anything else today.",
    "Small habits compound faster than big promises ever do.",
    "Ask yourself what you would do if the price doubled tomorrow.",
    "Friends often give advice that fit their life rather than yours.",
    "Your future self will thank you for one boring automatic rule.",
    "Put both paths side by side and the trade-off becomes clear.",
    "That gap looks tiny in week one and huge by the end of the year.",
    "Be suspicious of anything that promises results without effort.",
    "Good systems beat willpower because they keep working on bad days.",
    "If it feels complicated, break it into one step you can finish tonight.",
    "Every choice here has a cost, and naming it is half the battle.",
    "Nobody gets this perfect, and that is completely fine.",
    "Start with the smallest version that you will actually keep doing.",
    "Notice how the simple rule removes the need to decide every single time.",
    "This is where most guides stop, but the useful part comes next.",
    "Keep a short note of what worked, and repeat it next month.",
    "Think of it like a thermostat rather than a light switch.",
    "Comparing options in writing makes the better one obvious.",
    "Waiting for the perfect moment usually means never starting.",
    "One honest review each week catches mistakes before they grow.",
]


FILLER_SENTENCE_GROUPS = 3  # tests shrink this to render short videos


TAGS = ["", "truly", "honestly", "really", "clearly", "simply", "plainly", "frankly", "quietly", "calmly"]


def scene_text(i: int, words: int = 2) -> str:
    """Varied, number-free filler narration: no sentence repeats anywhere (the padding check would catch it)."""
    n = 3 * words
    out = []
    for j in range(n):
        k = i * n + j
        s, tag = SENTENCES[k % len(SENTENCES)], TAGS[(k // len(SENTENCES)) % len(TAGS)]
        out.append(f"{s[:-1]}, {tag}." if tag else s)
    return " ".join(out)


def fake_provider_config(extra: tuple[str, ...] = ()):
    """Three fake providers so diversity/fallback logic has something to choose from (plus `extra` ones)."""
    roles = ["research_summarizer", "brainstormer", "angle_selector", "scriptwriter", "voice_editor", "critic",
             "claim_checker", "repurposer", "test"]
    return {"providers": {
        name: {"enabled": True, "base_url": f"https://{name}.example/v1", "key_env": f"{name.upper()}_KEY",
               "commercial_use": "assumed",
               "models": [{"id": f"{name}-model", "roles": roles, "daily_requests": 1000, "priority": prio}]}
        for name, prio in (("alpha", 10), ("beta", 20), ("gamma", 30), *((n, 40 + i) for i, n in enumerate(extra)))}}


class ScriptedRouter(Router):
    """Real Router, but `_chat_once` is answered by `respond(role, prompt)` instead of HTTP."""

    def __init__(self, monkeypatch=None, failing: set[str] | None = None, extra: tuple[str, ...] = ()):
        if monkeypatch:
            for n in ("ALPHA", "BETA", "GAMMA", *extra):
                monkeypatch.setenv(f"{n.upper()}_KEY", "test-key")
        super().__init__(MemoryUsageStore(), client=httpx.Client(), provider_config=fake_provider_config(extra))
        self.failing = failing or set()
        self.calls: list[tuple[str, str]] = []

    def _chat_once(self, cand: Candidate, role, messages, *, json_mode, temperature, max_tokens):
        from studio.errors import QuotaError

        self.calls.append((role, cand.provider))
        if cand.provider in self.failing:
            self.usage.record(cand.provider, cand.model, role, success=False, input_tokens=0, output_tokens=0,
                              latency_ms=1, error="429")
            self.usage.open_circuit(cand.provider, 600, "quota")
            raise QuotaError(f"{cand.provider}: free quota reached")
        self.usage.record(cand.provider, cand.model, role, success=True, input_tokens=10, output_tokens=10,
                          latency_ms=1, error=None)
        return AIResult(json.dumps(respond(role, messages[1]["content"])), cand.provider, cand.model)


def _sources_in(prompt: str) -> list[tuple[str, str]]:
    return re.findall(r'<source id="(S\d+)"[^>]*>(.*?)</source>', prompt, flags=re.S)


def respond(role: str, prompt: str):
    if role == "brainstormer":
        refs = [s for s, _ in _sources_in(prompt)][:4] or ["S1"]
        topic = "budget" if "Money" in prompt else "AI assistant"
        return {"ideas": [
            {"title": f"The {topic} test: what the numbers really say", "angle": "We do the math step by step",
             "why_now": "New data this week", "source_refs": refs, "evergreen": False},
            {"title": f"Three {topic} myths, checked against the data", "angle": "Compare claims vs data",
             "why_now": "People keep asking", "source_refs": refs[1:], "evergreen": True},
        ]}
    if role == "research_summarizer":
        srcs = _sources_in(prompt)
        facts = []
        for i, (label, text) in enumerate(srcs[:4], 1):
            first = text.split(" — ")[-1].strip() or text
            facts.append({"key": f"F{i}", "text": first[:200], "source_ref": label, "data_period": "2026"})
        return {"facts": facts, "context": "Background from the sources.", "open_questions": []}
    if role == "scriptwriter" and "Plan the outline" in prompt:
        keys = re.findall(r"^(F\d+) \(S\d+", prompt, flags=re.M)
        bodies = [keys[i::3] for i in range(3)]
        return {"title": "The real numbers, explained", "hook": "Most advice skips the math. We won't.",
                "promise": "You will know exactly what to do next.",
                "hook_candidates": ["What if the obvious answer is wrong?"],
                "sections": [{"name": "The problem", "kind": "problem", "purpose": "Show the cost", "fact_keys": []},
                             {"name": "What you'll learn", "kind": "learn", "purpose": "Roadmap", "fact_keys": []}]
                            + [{"name": f"Step {n}", "kind": "body", "purpose": "Teach one step", "fact_keys": b}
                               for n, b in enumerate(bodies, 1)]
                            + [{"name": "Limits", "kind": "limits", "purpose": "Be honest", "fact_keys": []},
                               {"name": "Wrap-up", "kind": "wrap", "purpose": "Recap", "fact_keys": []}],
                "cta": "Subscribe for one useful idea every week." + (" This is general education, not personal advice."
                                                                       if "Penny" in prompt else "")}
    if role == "scriptwriter" and "Continue this section" in prompt:
        n = int(re.search(r"Section (\d+) \(", prompt).group(1))
        return {"scenes": [{"narration": scene_text(n * 7 + 6, 1), "visual": {"type": "title_card", "headline": "More"},
                            "claim_keys": []}], "claims": []}
    if role == "scriptwriter" and "Write ONLY section" in prompt:
        n = int(re.search(r"Write ONLY section (\d+)", prompt).group(1))
        use = re.search(r"Facts to use here: ([^.\n]*)", prompt).group(1)
        texts = dict(re.findall(r"^(F\d+) \(S\d+[^)]*\): (.*)$", prompt, flags=re.M))
        scenes, claims = [], []
        for fk in re.findall(r"F\d+", use):
            claims.append({"key": f"C{len(claims) + 1}", "text": texts[fk], "kind": "fact", "fact_refs": [fk]})
            lead = ["Start with the data:", "Now look at this:", "Here is the next piece:", "Then consider this:",
                    "One more thing matters:", "Put that next to this:"][(n + len(scenes)) % 6]
            scenes.append({"narration": f"{lead} {texts[fk]}. " + scene_text(n * 7 + len(scenes), 1),
                           "visual": {"type": "stat", "stat_value": "Key fact", "stat_label": texts[fk][:60]},
                           "claim_keys": [claims[-1]["key"]]})
        if not scenes or "body" not in prompt.split("Write ONLY section", 1)[1][:80]:
            scenes.append({"narration": scene_text(n * 7 + 5, FILLER_SENTENCE_GROUPS),
                           "visual": {"type": "list", "headline": "What to do",
                                      "items": ["Write it down", "Check the math", "Decide on Sunday"]}, "claim_keys": []})
        return {"scenes": scenes, "claims": claims}
    if role == "scriptwriter":
        if "Rewrite ONLY these scenes" in prompt:
            n = len(re.search(r"scene numbers \[([^\]]*)\]", prompt).group(1).split(","))
            return {"scenes": [{"narration": scene_text(k + 7, 1), "visual": {"type": "title_card", "headline": "Fixed"},
                                "claim_keys": []} for k in range(n)]}
        facts = re.findall(r"^(F\d+) \((S\d+)[^)]*\): (.*)$", prompt, flags=re.M)
        scenes, claims = [], []
        for i, (fk, _, ftext) in enumerate(facts, 1):
            claims.append({"key": f"C{i}", "text": ftext, "kind": "fact", "fact_refs": [fk]})
            scenes.append({"narration": f"{ftext}. " + scene_text(i, 1), "visual": {"type": "stat", "stat_value": "Key fact",
                           "stat_label": ftext[:60]}, "claim_keys": [f"C{i}"]})
        while len(scenes) < 6 + FILLER_SENTENCE_GROUPS:
            scenes.append({"narration": scene_text(len(scenes) + 3, FILLER_SENTENCE_GROUPS), "visual": {"type": "list", "headline": "What to do",
                           "items": ["Write it down", "Check the math", "Decide on Sunday"]}, "claim_keys": []})
        disclaimer = " This is general education, not personal advice." if "Penny" in prompt else ""
        return {"title": "The real numbers, explained", "hook": "Most advice skips the math. We won't.",
                "promise": "You will know exactly what to do next.",
                "hook_candidates": ["What if the obvious answer is wrong?"],
                "scenes": scenes, "claims": claims,
                "cta": "Subscribe for one useful idea every week." + disclaimer}
    if role == "claim_checker":
        out = []
        for key, block in re.findall(r'<evidence id="(C\d+)">(.*?)</evidence>', prompt, flags=re.S):
            passage = re.search(r"Passage: (.*)", block)
            quote = passage.group(1).split(" ")[:12] if passage else []
            out.append({"key": key, "status": "supported" if passage else "unsupported",
                        "supporting_quote": " ".join(quote), "note": ""})
        return {"verdicts": out}
    if role == "voice_editor":
        scenes = json.loads(prompt.split("Scenes:\n", 1)[1].split("\n\nReturn JSON", 1)[0])
        return {"hook": "Most advice skips the math. Not here.",
                "scenes": [{"n": s["n"], "narration": s["narration"].replace("Here is", "Here's")} for s in scenes]}
    if role == "critic":
        return {"hook": 8, "originality": 8, "clarity": 8, "pacing": 8, "value": 8, "fixes": [], "weak_scenes": []}
    if role == "angle_selector":
        return {"best": 0, "reason": "clearest"}
    if role == "repurposer":
        def short_scene(k):
            return {"narration": scene_text(k, 1), "visual": {"type": "title_card", "headline": "Quick version"},
                    "claim_keys": []}
        return {"youtube_title": "The real numbers, explained", "youtube_description": "What we found.\n\n[SOURCES]",
                "tags": ["budget", "money tips"], "thumbnail_headlines": ["The real numbers", "Do the math", "Myth vs data"],
                "x_post": "Most advice skips the math. Which number surprised you most?",
                "facebook_post": "We did the math so you don't have to. Here's what it means for your week.",
                "shorts": [{"title": "The 30-second version", "hook": "Here's the short version.",
                            "scenes": [short_scene(1), short_scene(2)], "caption": "The short version",
                            "hashtags": ["money", "tips"]},
                           {"title": "One thing to try today", "hook": "Try this tonight.",
                            "scenes": [short_scene(4), short_scene(5)], "caption": "Try this",
                            "hashtags": ["tips"]}]}
    if role == "test":
        return "ready"
    raise AssertionError(f"unexpected role {role}")


def fake_sources(conn, channel="money", n=4):
    from studio import db

    ids = []
    for i in range(n):
        row = db.one(conn, """insert into research_sources (adapter, title, publisher, url, published_at, summary,
                              credibility, topic, fresh_until, content_hash)
                              values ('fred', %s, 'FRED', %s, now() - interval '1 day', %s, 'primary_data', %s,
                                      now() + interval '20 days', %s) returning id""",
                     (f"{'Budget' if channel == 'money' else 'AI assistant'} data point {i}",
                      f"https://example.org/{channel}/{i}",
                      f"The household savings rate was {4 + i}.{i} percent in September 2026 according to official data",
                      channel, f"hash-{channel}-{i}"))
        ids.append(row["id"])
    return ids
