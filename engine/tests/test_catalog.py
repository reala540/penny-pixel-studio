import httpx

from studio.ai import catalog
from studio.ai.router import Router
from studio.ai.usage import MemoryUsageStore


def test_substitute_prefers_newest_stable_model_of_same_family():
    avail = ["gemini-3-pro-preview", "gemini-3.1-pro", "gemini-3.1-flash", "gemini-embedding-001", "gemini-3.1-pro-tts"]
    assert catalog.pick_substitute("gemini-2.5-pro", avail) == "gemini-3.1-pro"
    assert catalog.pick_substitute("gemini-2.5-flash", avail) == "gemini-3.1-flash"
    assert catalog.pick_substitute("gpt-oss-20b", ["gpt-4o", "gpt-oss-120b"]) == "gpt-oss-120b"
    assert catalog.pick_substitute("z-ai/glm-5.2", ["meta/llama-4"]) is None


def test_openrouter_substitutes_stay_free():
    avail = ["google/gemma-5-27b-it", "google/gemma-5-27b-it:free"]
    assert catalog.pick_substitute("google/gemma-4-31b-it:free", avail, free_only=True) == "google/gemma-5-27b-it:free"


def test_refresh_and_router_use_the_substitute(monkeypatch):
    monkeypatch.setenv("TESTP_KEY", "k")
    cfg = {"providers": {"testp": {"enabled": True, "base_url": "https://p.test/v1", "key_env": "TESTP_KEY",
                                   "models": [{"id": "gemini-2.5-pro", "roles": ["critic"], "priority": 1},
                                              {"id": "old-thing-1", "roles": ["critic"], "priority": 2}]}}}
    client = httpx.Client(transport=httpx.MockTransport(
        lambda req: httpx.Response(200, json={"data": [{"id": "models/gemini-3.1-pro"}]})))
    found = catalog.refresh(cfg, client)
    assert found["testp"]["missing"] == {"gemini-2.5-pro": "gemini-3.1-pro", "old-thing-1": None}
    store = MemoryUsageStore(provider_overrides={"testp": {"enabled": True, "missing": found["testp"]["missing"]}})
    models = [c.model for c in Router(store, provider_config=cfg).candidates("critic")]
    assert models == ["gemini-3.1-pro"]


def test_unlisted_provider_keeps_configured_models(monkeypatch):
    monkeypatch.setenv("TESTP_KEY", "k")
    cfg = {"providers": {"testp": {"base_url": "https://p.test/v1", "key_env": "TESTP_KEY",
                                   "models": [{"id": "m1", "roles": ["critic"]}]}}}
    client = httpx.Client(transport=httpx.MockTransport(lambda req: httpx.Response(404)))
    assert catalog.refresh(cfg, client) == {"testp": {"listed": False, "missing": {}}}


def test_reads_the_replacement_a_provider_suggests():
    msg = ('404 "message": "This model models/gemini-2.5-pro is no longer available to new users. '
           'Please update your code to use models/gemini-3.1-pro-preview for the latest features"')
    assert catalog.suggested_replacement(msg) == "gemini-3.1-pro-preview"
    assert catalog.suggested_replacement("404 not found") is None


def test_a_hosted_name_is_the_same_model_not_a_reason_to_swap_it():
    listed = ["glm-4.7", "glm-5.3", "minimax-m2.5", "gpt-oss:120b"]
    assert catalog.pick_substitute("glm-4.7:cloud", listed) == "glm-4.7"      # not the newer (paid) glm-5.3
    assert catalog.pick_substitute("minimax-m2.5-cloud", listed) == "minimax-m2.5"
    assert catalog.pick_substitute("gpt-oss:120b-cloud", listed) == "gpt-oss:120b"
