"""Multiple keys per provider: strategies, caps, failover rules, concurrency and secrecy."""

import json
import threading
import time
from collections import Counter

import httpx
import pytest

from studio import db, oauth
from studio.ai.credentials import Credential, ProviderSettings, backoff_seconds, mask
from studio.ai.router import Router
from studio.ai.usage import DbUsageStore, MemoryUsageStore
from studio.errors import QuotaError

KEYS = {"key-aaaa-1111": "A", "key-bbbb-2222": "B", "key-cccc-3333": "C"}


def cfg():
    return {"providers": {
        "gem": {"enabled": True, "base_url": "https://gem.test/v1", "key_env": "GEM_KEY", "commercial_use": "assumed",
                "models": [{"id": "g1", "roles": ["critic"], "priority": 10}]},
        "other": {"enabled": True, "base_url": "https://other.test/v1", "key_env": "OTHER_KEY", "commercial_use": "assumed",
                  "models": [{"id": "o1", "roles": ["critic"], "priority": 20}]},
    }}


def ok(content="fine", tin=100, tout=50):
    return httpx.Response(200, json={"choices": [{"message": {"content": content}}],
                                     "usage": {"prompt_tokens": tin, "completion_tokens": tout}})


def key_of(req):
    return KEYS.get(req.headers.get("authorization", "").removeprefix("Bearer "), "env")


@pytest.fixture(autouse=True)
def env(monkeypatch):
    monkeypatch.delenv("GEM_KEY", raising=False)
    monkeypatch.setenv("OTHER_KEY", "other-key-9999")


def make(handler, creds, strategy="priority", sleeps=None, **settings):
    store = MemoryUsageStore(creds=creds, settings={"gem": ProviderSettings(key_strategy=strategy, **settings)})
    return Router(store, client=httpx.Client(transport=httpx.MockTransport(handler)), provider_config=cfg(),
                  sleep=(sleeps.append if sleeps is not None else (lambda s: None))), store


def three(**kw):
    return [Credential(f"id-{n}", "gem", n, k, priority=i + 1, **kw) for i, (k, n) in enumerate(KEYS.items())]


def test_round_robin_spreads_requests_across_keys():
    seen = []
    r, _ = make(lambda req: seen.append(key_of(req)) or ok(), three(), "round_robin")
    for _ in range(6):
        r.complete("critic", "hi")
    assert seen == ["A", "B", "C", "A", "B", "C"]


def test_priority_uses_best_key_until_its_daily_cap():
    seen = []
    creds = three()
    creds[0].daily_request_cap = 2
    r, _ = make(lambda req: seen.append(key_of(req)) or ok(), creds, "priority")
    for _ in range(4):
        r.complete("critic", "hi")
    assert seen == ["A", "A", "B", "B"]


def test_least_utilized_prefers_most_remaining_capacity():
    seen = []
    creds = three()
    creds[0].daily_request_cap, creds[1].daily_request_cap, creds[2].daily_request_cap = 2, 10, 4
    r, _ = make(lambda req: seen.append(key_of(req)) or ok(), creds, "least_utilized")
    for _ in range(6):
        r.complete("critic", "hi")
    # share used after each call: A 1/2, B 1/10, C 1/4 ... the key with the smallest used share goes next
    assert seen == ["A", "B", "C", "B", "B", "C"]


def test_health_strategy_avoids_a_failing_key():
    calls = []

    def handler(req):
        calls.append(key_of(req))
        return httpx.Response(503) if key_of(req) == "A" else ok()

    r, _ = make(handler, three(), "health", max_retries=0)
    r.complete("critic", "hi")            # A fails once, B answers
    calls.clear()
    for _ in range(3):
        r.complete("critic", "hi")
    assert "A" not in calls               # A now has the worst recent error rate


def test_weighted_distribution_follows_percentages():
    seen = []
    creds = three()
    creds[0].weight, creds[1].weight, creds[2].weight = 6, 3, 1
    r, _ = make(lambda req: seen.append(key_of(req)) or ok(), creds, "weighted")
    for _ in range(40):
        r.complete("critic", "hi")
    c = Counter(seen)
    assert (c["A"], c["B"], c["C"]) == (24, 12, 4)


def test_transient_errors_retry_with_bounded_jittered_backoff_then_next_key():
    calls = []
    sleeps = []

    def handler(req):
        calls.append(key_of(req))
        return httpx.Response(502) if key_of(req) == "A" else ok()

    r, _ = make(handler, three(), "priority", sleeps=sleeps, max_retries=2)
    res = r.complete("critic", "hi")
    assert calls == ["A", "A", "A", "B"]          # 1 try + 2 retries on A, then B: never endless
    assert res.credential_label == "B"
    assert len(sleeps) == 2 and sleeps[0] <= 0.5 and sleeps[1] <= 1.0
    assert all(0 <= backoff_seconds(10) <= 20 for _ in range(50))


def test_rate_limit_rests_the_whole_shared_quota_group_and_moves_provider():
    hosts = []

    def handler(req):
        hosts.append((req.url.host, key_of(req)))
        if req.url.host == "gem.test":
            return httpx.Response(429, headers={"retry-after": "120"})
        return ok()

    r, store = make(handler, three(), "priority")
    res = r.complete("critic", "hi")
    assert hosts == [("gem.test", "A"), ("other.test", "env")]   # siblings B and C are NOT tried
    assert res.provider == "other" and res.substituted_from == "gem/g1"
    assert store.circuit_open("gem")


def test_separately_attested_account_may_take_over_after_rate_limit():
    hosts = []
    creds = three()
    creds[1].quota_group = "gem:family-account"     # attested separate account with its own allowance

    def handler(req):
        hosts.append(key_of(req))
        return httpx.Response(429) if key_of(req) == "A" else ok()

    r, _ = make(handler, creds, "priority")
    assert r.complete("critic", "hi").credential_label == "B"
    assert hosts == ["A", "B"]


def test_rejected_key_is_marked_invalid_and_skipped():
    calls = []

    def handler(req):
        calls.append(key_of(req))
        return httpx.Response(401) if key_of(req) == "A" else ok()

    r, store = make(handler, three(), "priority")
    r.complete("critic", "hi")
    calls.clear()
    r.complete("critic", "hi")
    assert calls == ["B"] and store.health["id-A"] == "invalid"


def test_monthly_spend_cap_uses_estimated_cost():
    seen = []
    creds = three()
    creds[0].input_usd_per_mtok, creds[0].output_usd_per_mtok, creds[0].monthly_spend_cap_usd = 1000.0, 1000.0, 0.2
    r, store = make(lambda req: seen.append(key_of(req)) or ok(tin=100, tout=50), creds, "priority")
    for _ in range(3):
        r.complete("critic", "hi")
    assert seen == ["A", "A", "B"]                  # each call ≈ $0.15 estimated; cap $0.20
    rows = [c for c in store.calls if c["credential_id"] == "id-A"]
    assert all(c["cost_source"] == "estimated" for c in rows)
    assert all(c["cost_source"] == "none" for c in store.calls if c["credential_id"] == "id-B")


def test_no_eligible_key_is_a_clear_error():
    creds = three()
    for c in creds:
        c.daily_request_cap = 0
    store = MemoryUsageStore(creds=creds)
    r = Router(store, client=httpx.Client(transport=httpx.MockTransport(lambda req: ok())),
               provider_config={"providers": {"gem": cfg()["providers"]["gem"]}})
    with pytest.raises(QuotaError, match="No free AI provider|no eligible API key"):
        r.complete("critic", "hi")


def test_parallel_requests_respect_per_key_concurrency():
    lock = threading.Lock()
    active, peak = Counter(), Counter()

    def handler(req):
        k = key_of(req)
        with lock:
            active[k] += 1
            peak[k] = max(peak[k], active[k])
        time.sleep(0.05)
        with lock:
            active[k] -= 1
        return ok()

    creds = three(max_concurrency=1)
    r, _ = make(handler, creds, "round_robin", request_timeout_s=10)
    threads = [threading.Thread(target=r.complete, args=("critic", "hi")) for _ in range(9)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert max(peak.values()) == 1 and sum(peak.values()) >= 2


def test_keys_never_appear_in_errors_or_usage_rows():
    def handler(req):
        return httpx.Response(500, text="upstream exploded")

    r, store = make(handler, three(), "priority", max_retries=0)
    with pytest.raises(Exception) as exc:
        r.complete("critic", "hi", exclude={"other"})
    text = str(exc.value) + json.dumps(store.calls, default=str)
    assert not any(k in text for k in KEYS)
    assert mask("key-aaaa-1111") == "••••1111" and mask("short") == "••••"


def test_database_pool_decrypts_keys_records_credential_and_cost(synced, monkeypatch):
    c = synced
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    db.run(c, "update ai_providers set key_strategy='priority' where name='gemini'")
    cred = db.one(c, """insert into ai_credentials (provider, label, owner_name, authorized_use, key_hint, quota_group,
                        input_usd_per_mtok, output_usd_per_mtok)
                        values ('gemini','Family key','Sam','Scripts for the studio','••••1111','gemini', 1, 2)
                        returning id""")["id"]
    db.run(c, "insert into ai_credential_secrets (credential_id, ciphertext) values (%s,%s)",
           (cred, oauth.encrypt({"key": "key-aaaa-1111"})))
    seen = []
    providers = {"providers": {"gemini": {"enabled": True, "base_url": "https://g.test/v1", "key_env": "GEMINI_API_KEY",
                                          "commercial_use": "assumed",
                                          "models": [{"id": "gemini-3.8-flash", "roles": ["critic"], "priority": 1}]}}}
    r = Router(DbUsageStore(c), client=httpx.Client(transport=httpx.MockTransport(
        lambda req: seen.append(key_of(req)) or ok(tin=1_000_000, tout=1_000_000))), provider_config=providers)
    assert r.complete("critic", "hi").credential_label == "Family key"
    row = db.one(c, "select credential_id, cost_usd, cost_source from provider_usage order by id desc limit 1")
    assert seen == ["A"] and str(row["credential_id"]) == str(cred)
    assert float(row["cost_usd"]) == 3.0 and row["cost_source"] == "estimated"
    assert db.one(c, "select health from ai_credentials where id=%s", (cred,))["health"] == "healthy"
    # a key that can no longer be decrypted is never used and is flagged for replacement
    db.run(c, "update ai_credential_secrets set ciphertext='garbage' where credential_id=%s", (cred,))
    r2 = Router(DbUsageStore(c), client=httpx.Client(transport=httpx.MockTransport(lambda req: ok())), provider_config=providers)
    with pytest.raises(QuotaError):
        r2.complete("critic", "hi")
    assert db.one(c, "select health from ai_credentials where id=%s", (cred,))["health"] == "invalid"
