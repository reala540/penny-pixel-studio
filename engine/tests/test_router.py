import json

import httpx
import pytest
from pydantic import BaseModel

from studio import jobs
from studio.ai.router import Router, extract_json
from studio.ai.usage import MemoryUsageStore
from studio.errors import QuotaError


class Out(BaseModel):
    answer: str


def cfg(**over):
    base = {"providers": {
        "first": {"enabled": True, "base_url": "https://first.test/v1", "key_env": "FIRST_KEY", "commercial_use": "assumed",
                  "models": [{"id": "f1", "roles": ["critic"], "daily_requests": 2, "priority": 10}]},
        "second": {"enabled": True, "base_url": "https://second.test/v1", "key_env": "SECOND_KEY", "commercial_use": "assumed",
                   "models": [{"id": "s1", "roles": ["critic"], "daily_requests": 100, "priority": 20}]},
        "nocommercial": {"enabled": True, "base_url": "https://nc.test/v1", "key_env": "NC_KEY", "commercial_use": "no",
                         "models": [{"id": "n1", "roles": ["critic"], "daily_requests": 100, "priority": 1}]},
        "nokey": {"enabled": True, "base_url": "https://nokey.test/v1", "key_env": "MISSING_KEY", "commercial_use": "assumed",
                  "models": [{"id": "k1", "roles": ["critic"], "daily_requests": 100, "priority": 1}]},
    }}
    base["providers"].update(over)
    return base


def reply(content, status=200):
    return httpx.Response(status, json={"choices": [{"message": {"content": content}}],
                                        "usage": {"prompt_tokens": 5, "completion_tokens": 3}})


@pytest.fixture(autouse=True)
def keys(monkeypatch):
    monkeypatch.setenv("FIRST_KEY", "a")
    monkeypatch.setenv("SECOND_KEY", "b")
    monkeypatch.setenv("NC_KEY", "c")
    monkeypatch.delenv("MISSING_KEY", raising=False)


def make(handler, usage=None):
    return Router(usage or MemoryUsageStore(), client=httpx.Client(transport=httpx.MockTransport(handler)),
                  provider_config=cfg())


def test_excludes_non_commercial_and_missing_keys():
    r = make(lambda req: reply("x"))
    names = [c.provider for c in r.candidates("critic")]
    assert names == ["first", "second"]


def test_falls_back_on_rate_limit_and_opens_circuit():
    seen = []

    def handler(req):
        seen.append(req.url.host)
        if req.url.host == "first.test":
            return httpx.Response(429, json={"error": "rate"})
        return reply(json.dumps({"answer": "ok"}))

    usage = MemoryUsageStore()
    r = make(handler, usage)
    res = r.complete("critic", "hi", schema=Out)
    assert res.provider == "second" and res.data.answer == "ok"
    assert usage.circuit_open("first")
    assert [c.provider for c in r.candidates("critic")] == ["second"]


def test_auth_error_skips_provider_for_a_day():
    def handler(req):
        if req.url.host == "first.test":
            return httpx.Response(401, json={"error": "bad key"})
        return reply("fine")

    usage = MemoryUsageStore()
    r = make(handler, usage)
    assert r.complete("critic", "hi").provider == "second"
    assert usage.circuit_open("first")


def test_daily_free_limit_is_respected():
    r = make(lambda req: reply("ok"))
    for _ in range(2):
        assert r.complete("critic", "hi").provider == "first"
    assert r.complete("critic", "hi").provider == "second"  # first hit its 2/day free limit


def test_invalid_json_gets_one_repair_then_next_provider():
    calls = {"n": 0}

    def handler(req):
        calls["n"] += 1
        body = json.loads(req.content)
        if req.url.host == "first.test" and len(body["messages"]) == 2:
            return reply("not json at all")
        if req.url.host == "first.test":
            return reply('```json\n{"answer": "repaired"}\n```')
        return reply(json.dumps({"answer": "second"}))

    res = make(handler).complete("critic", "hi", schema=Out)
    assert res.data.answer == "repaired" and res.provider == "first"


def test_quota_error_when_everything_exhausted():
    r = make(lambda req: httpx.Response(429))
    with pytest.raises(QuotaError):
        r.complete("critic", "hi")


def test_payment_required_is_never_retried_as_paid():
    def handler(req):
        if req.url.host == "first.test":
            return httpx.Response(402, json={"error": "payment required"})
        return reply("ok")

    usage = MemoryUsageStore()
    res = make(handler, usage).complete("critic", "hi")
    assert res.provider == "second" and usage.circuit_open("first")


def test_active_job_is_attributed_and_context_is_reset():
    usage = MemoryUsageStore()
    router = make(lambda req: reply("ok"), usage)
    with jobs.job_context("mission-123"):
        router.complete("critic", "hello")
    assert usage.calls[-1]["job_id"] == "mission-123"
    router.complete("critic", "hello again")
    assert usage.calls[-1]["job_id"] is None


def test_extract_json_variants():
    assert extract_json('{"a":1}') == {"a": 1}
    assert extract_json('Sure! ```json\n{"a": 2}\n``` hope that helps') == {"a": 2}
    assert extract_json('prefix {"a": 3} suffix') == {"a": 3}


def test_equal_rank_rotates_to_the_least_used_model():
    usage = MemoryUsageStore()
    r = Router(usage, client=httpx.Client(transport=httpx.MockTransport(lambda req: reply("x"))), provider_config=cfg(
        first={"enabled": True, "base_url": "https://first.test/v1", "key_env": "FIRST_KEY", "commercial_use": "assumed",
               "models": [{"id": "f1", "roles": ["critic"], "priority": 20}]}))
    assert [c.provider for c in r.candidates("critic")] == ["first", "second"]  # a tie: alphabetical
    r.complete("critic", "hi")
    assert [c.provider for c in r.candidates("critic")] == ["second", "first"]  # first was used, second goes next
    r.complete("critic", "hi")
    assert [c.provider for c in r.candidates("critic")] == ["first", "second"]


def test_extra_accounts_of_one_company_are_not_independent():
    seen = []

    def handler(req):
        seen.append(req.url.host)
        return reply("ok")

    r = Router(MemoryUsageStore(), client=httpx.Client(transport=httpx.MockTransport(handler)), provider_config={"providers": {
        "cloudflare2": {"enabled": True, "base_url": "https://cf2.test/v1", "key_env": "FIRST_KEY", "commercial_use": "assumed",
                        "models": [{"id": "llama", "roles": ["critic"], "priority": 1}]},
        "other": {"enabled": True, "base_url": "https://other.test/v1", "key_env": "SECOND_KEY", "commercial_use": "assumed",
                  "models": [{"id": "o1", "roles": ["critic"], "priority": 50}]},
    }})
    res = r.complete("critic", "check this", exclude={"cloudflare"})  # the writer was the main Cloudflare account
    assert res.provider == "other" and seen == ["other.test"]
