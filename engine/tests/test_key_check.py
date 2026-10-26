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
def test_a_retired_model_is_switched_off_on_every_account_of_that_service(synced, monkeypatch):
    c = synced
    _add_provider(c, "bluesminds", [("moonshotai/kimi-k3", ["scriptwriter"]), ("nvidia/nemotron-3-ultra-550b-a55b", ["scriptwriter"])])
    _add_provider(c, "bluesminds2", [("moonshotai/kimi-k3", ["scriptwriter"])], key="sk-two")
    db.run(c, "update ai_providers set base_url = 'https://bluesminds.test/v1' where name like 'bluesminds%'")
    sent = []
    monkeypatch.setattr("studio.notify.send", lambda conn, kind, title, body="", **kw: sent.append((kind, title)) or True)

    def answer(req: httpx.Request):
        body = json.loads(req.content)
        if body["model"] == "moonshotai/kimi-k3":
            return httpx.Response(410, json={"error": {"message": "The model 'moonshotai/kimi-k3' has reached its end of life"}})
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}], "usage": {}})
    router = Router(DbUsageStore(c), client=_mock_client(answer))
    assert router.complete("scriptwriter", "write").model == "nvidia/nemotron-3-ultra-550b-a55b"
    off = db.all_(c, """select provider from ai_model_configs where model='moonshotai/kimi-k3' and pause_reason='retired'
                        and enabled and next_check_at > now() + interval '6 days' order by provider""")
    assert [r["provider"] for r in off] == ["bluesminds", "bluesminds2"]   # both accounts, in one go
    assert sent == [("ai_model_retired", "AI model switched off: moonshotai/kimi-k3")]
    assert db.one(c, "select details from audit_logs where action='ai_model_paused'")["details"]["providers"] == ["bluesminds", "bluesminds2"]



def test_paused_models_are_retested_and_come_back_by_themselves(synced, monkeypatch):
    from studio.ai import health

    c = synced
    _add_provider(c, "bluesminds", [("moonshotai/kimi-k3", ["scriptwriter"]), ("nvidia/nemotron-3-ultra-550b-a55b", ["scriptwriter"])])
    db.run(c, """update ai_model_configs set pause_reason='retired', paused_at=now(), next_check_at=now() - interval '1 minute',
                 checks=0 where provider='bluesminds'""")
    sent = []
    monkeypatch.setattr("studio.notify.send", lambda conn, kind, title, body="", **kw: sent.append((kind, title, body)) or True)
    working = {"nvidia/nemotron-3-ultra-550b-a55b"}

    def answer(req: httpx.Request):
        if req.url.path.endswith("/models"):
            return httpx.Response(404)
        if json.loads(req.content)["model"] in working:
            return httpx.Response(200, json={"choices": [{"message": {"content": "ready"}}], "usage": {}})
        return httpx.Response(410, json={"error": {"message": "reached its end of life"}})
    monkeypatch.setattr(httpx, "Client", lambda *a, **k: _mock_client(answer))
    out = health.recheck(c)
    assert [b["model"] for b in out["back"]] == ["nvidia/nemotron-3-ultra-550b-a55b (bluesminds)"]
    assert [s["checks"] for s in out["still"]] == [1]
    rows = {r["model"]: r for r in db.all_(c, "select * from ai_model_configs where provider='bluesminds'")}
    assert rows["nvidia/nemotron-3-ultra-550b-a55b"]["pause_reason"] is None                       # back in the team
    assert rows["moonshotai/kimi-k3"]["next_check_at"] > db.one(c, "select now() + interval '6 days' t")["t"]
    assert [k for k, *_ in sent] == ["ai_model_back"]                                               # one grouped notice
    assert health.recheck(c) == {"back": [], "still": [], "given_up": []}                           # nothing due now
    # after the 4th weekly re-test it stops trying and asks the owner; the model stays paused, nothing is deleted
    db.run(c, "update ai_model_configs set checks=3, next_check_at=now() - interval '1 minute' where model='moonshotai/kimi-k3'")
    out = health.recheck(c)
    assert out["given_up"] and sent[-1][0] == "ai_model_given_up"
    left = db.one(c, "select pause_reason, next_check_at, enabled from ai_model_configs where model='moonshotai/kimi-k3'")
    assert left == {"pause_reason": "retired", "next_check_at": None, "enabled": True}


def test_a_rejected_key_tells_the_owner_once_a_day(synced, monkeypatch):
    c = synced
    _add_provider(c, "xkiro", [("qwen/qwen3.8-max:free", ["critic"])])
    sent = []
    monkeypatch.setattr("studio.notify.send", lambda conn, kind, title, body="", **kw: sent.append((kind, kw.get("dedupe_key"))) or True)
    router = Router(DbUsageStore(c), client=_mock_client(lambda req: httpx.Response(401, json={"error": "bad key"})))
    for _ in range(2):
        try:
            router.complete("critic", "x", only=router.candidates("critic")[0]) if router.candidates("critic") else None
        except Exception:
            pass
    assert sent and sent[0][0] == "ai_key_rejected" and sent[0][1].startswith("keyrejected:")  # one per key per day
    assert db.one(c, "select health from ai_credentials where provider='xkiro'")["health"] == "invalid"
