"""The AI key check tests what the studio really uses: built-in and added providers, every switched-on model,
models added in the AI API Manager, with the saved keys."""

import json

import httpx

from studio import cli, db, oauth
from studio.ai.router import Router
from studio.ai.usage import DbUsageStore


def _add_provider(conn, name, models, key="sk-test"):
    db.run(conn, "insert into ai_providers (name, enabled, base_url, commercial_use_ok) values (%s, true, %s, true)",
           (name, f"https://{name}.test/v1"))
    for model, roles in models:
        db.run(conn, """insert into ai_model_configs (provider, model, roles, priority, enabled, roles_custom)
                        values (%s,%s,%s,40,true,true)""", (name, model, roles))
    cred = db.one(conn, """insert into ai_credentials (provider, label, owner_name, authorized_use, key_hint, quota_group,
                                                       separate_account_attested)
                           values (%s,'k1','owner','testing','••test',%s,true) returning id""", (name, f"{name}:g1"))
    db.run(conn, "insert into ai_credential_secrets (credential_id, ciphertext) values (%s,%s)",
           (cred["id"], oauth.encrypt({"key": key})))


def test_models_added_in_the_app_are_used_and_checked(synced, monkeypatch):
    c = synced
    _add_provider(c, "xkiro", [("qwen/qwen3.8-max:free", ["critic", "claim_checker"]),
                               ("qwen/qwen3.7-flash:free", ["claim_checker"])])
    db.run(c, """insert into ai_model_configs (provider, model, roles, priority, enabled, roles_custom)
                 values ('gemini','gemini-2.5-flash', array['critic'], 30, true, true)""")
    monkeypatch.setenv("GEMINI_API_KEY", "g-test")
    router = Router(DbUsageStore(c))
    assert "gemini-2.5-flash" in [m["id"] for m in router.cfg["providers"]["gemini"]["models"]]  # no longer ignored
    assert {"qwen/qwen3.8-max:free", "gemini-2.5-flash"} <= {x.model for x in router.candidates("critic")}

    asked = []

    def answer(req: httpx.Request):
        body = json.loads(req.content) if req.content else {}
        if req.url.path.endswith("/models"):
            return httpx.Response(404)
        asked.append((req.url.host, body.get("model"), req.headers.get("authorization")))
        if body.get("model") == "qwen/qwen3.7-flash:free":
            return httpx.Response(402, json={"error": {"message": "payment required"}})
        return httpx.Response(200, json={"choices": [{"message": {"content": "ready"}}], "usage": {}})
    monkeypatch.setattr(httpx, "Client", lambda *a, **k: _mock_client(answer))  # no network in tests
    results = {r["provider"]: r for r in cli.run_provider_check(c)}
    xk = results["xkiro"]
    assert xk["status"] == "ok" and xk["note"].startswith("1 of 2 models work")
    assert "qwen/qwen3.7-flash:free: this model isn't free on your plan" in xk["error"]
    assert ("xkiro.test", "qwen/qwen3.8-max:free", "Bearer sk-test") in asked            # the saved key is used
    assert any(m == "gemini-2.5-flash" for _, m, _ in asked)                             # the app-added model too
    assert db.get_setting(c, "provider_check")["results"]


_REAL_CLIENT = httpx.Client


def _mock_client(handler):
    return _REAL_CLIENT(transport=httpx.MockTransport(handler))


def test_one_service_can_be_tested_on_its_own(synced, monkeypatch):
    c = synced
    _add_provider(c, "xkiro", [("qwen/qwen3.8-max:free", ["critic"])])
    _add_provider(c, "bluesminds", [("moonshotai/kimi-k3", ["scriptwriter"])])
    db.set_setting(c, "provider_check", {"results": [{"provider": "bluesminds", "status": "ok", "note": "earlier"}]})
    asked = []

    def answer(req: httpx.Request):
        if req.url.path.endswith("/models"):
            return httpx.Response(404)
        asked.append(req.url.host)
        return httpx.Response(200, json={"choices": [{"message": {"content": "ready"}}], "usage": {}})
    monkeypatch.setattr(httpx, "Client", lambda *a, **k: _mock_client(answer))
    out = cli.run_provider_check(c, only="xkiro")
    assert [r["provider"] for r in out] == ["xkiro"] and set(asked) == {"xkiro.test"}  # nothing else was called
    saved = {r["provider"]: r for r in db.get_setting(c, "provider_check")["results"]}
    assert saved["bluesminds"]["note"] == "earlier" and saved["xkiro"]["status"] == "ok"  # others keep their result
