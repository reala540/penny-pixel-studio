"""Usage + health tracking for AI providers (per-day request/token counts, circuit breakers)."""

from __future__ import annotations

import functools
import threading
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Protocol

from .. import db
from .credentials import Credential, ProviderSettings, utc_month_start


class UsageStore(Protocol):
    def requests_today(self, provider: str, model: str) -> int: ...
    def tokens_today(self, provider: str, model: str) -> int: ...
    def record(self, provider: str, model: str, role: str, *, success: bool, input_tokens: int,
               output_tokens: int, latency_ms: int, error: str | None, job_id=None, credential_id=None,
               cost_usd: float = 0.0, cost_source: str = "none") -> None: ...
    def circuit_open(self, provider: str) -> bool: ...
    def open_circuit(self, provider: str, seconds: int, reason: str) -> None: ...
    def mark_success(self, provider: str) -> None: ...
    def error_rate(self, provider: str, model: str) -> float: ...
    def overrides(self) -> dict[str, dict]: ...


@dataclass
class MemoryUsageStore:
    """In-process store for tests and offline runs."""

    calls: list[dict] = field(default_factory=list)
    circuits: dict[str, datetime] = field(default_factory=dict)
    provider_overrides: dict[str, dict] = field(default_factory=dict)
    creds: list[Credential] = field(default_factory=list)        # extra keys (tests / offline)
    settings: dict[str, ProviderSettings] = field(default_factory=dict)
    rests: dict[str, datetime] = field(default_factory=dict)      # credential slot or "group:<provider>:<group>"
    health: dict[str, str] = field(default_factory=dict)

    def _today(self, provider, model):
        today = date.today()
        return [c for c in self.calls if c["provider"] == provider and c["model"] == model and c["day"] == today]

    def requests_today(self, provider, model):
        return len(self._today(provider, model))

    def tokens_today(self, provider, model):
        return sum(c["in"] + c["out"] for c in self._today(provider, model))

    def record(self, provider, model, role, *, success, input_tokens, output_tokens, latency_ms, error, job_id=None,
               credential_id=None, cost_usd=0.0, cost_source="none"):
        self.calls.append({"provider": provider, "model": model, "role": role, "success": success,
                           "in": input_tokens, "out": output_tokens, "day": date.today(), "error": error,
                           "job_id": job_id, "credential_id": credential_id, "cost": cost_usd,
                           "cost_source": cost_source, "at": datetime.now(timezone.utc)})

    def circuit_open(self, provider):
        until = self.circuits.get(provider)
        return bool(until and until > datetime.now(timezone.utc))

    def open_circuit(self, provider, seconds, reason):
        self.circuits[provider] = datetime.now(timezone.utc) + timedelta(seconds=seconds)

    def mark_success(self, provider):
        self.circuits.pop(provider, None)

    def error_rate(self, provider, model):
        # a rejected key is that key's problem, not the provider's reliability
        recent = [c for c in self.calls if c["provider"] == provider and c["model"] == model
                  and not str(c.get("error") or "").endswith(" auth")][-20:]
        if not recent:
            return 0.0
        return sum(1 for c in recent if not c["success"]) / len(recent)

    def overrides(self):
        return self.provider_overrides

    # credentials ---------------------------------------------------------------
    def credential_rows(self, provider):
        return [c for c in self.creds if c.provider == provider]

    def provider_settings(self, provider):
        return self.settings.get(provider, ProviderSettings())

    def credential_resting(self, cred, now):
        for k in (cred.slot, f"group:{cred.provider}:{cred.quota_group}"):
            if self.rests.get(k) and self.rests[k] > now:
                return True
        return False

    def credential_usage(self, cred):
        mine = [c for c in self.calls if c["provider"] == cred.provider and c.get("credential_id") == cred.id]
        today = [c for c in mine if c["day"] == date.today()]
        month = [c for c in mine if c["at"] >= utc_month_start()]
        recent = mine[-20:]
        return {"requests_today": len(today), "tokens_today": sum(c["in"] + c["out"] for c in today),
                "cost_month": sum(c["cost"] for c in month),
                "error_rate": (sum(1 for c in recent if not c["success"]) / len(recent)) if recent else 0.0}

    def credential_health(self, cred, health, rest_seconds, error, reset=False):
        self.health[cred.slot] = health
        if reset:
            self.rests.pop(cred.slot, None)
            self.rests.pop(f"group:{cred.provider}:{cred.quota_group}", None)
        elif rest_seconds:
            self.rests[cred.slot] = datetime.now(timezone.utc) + timedelta(seconds=rest_seconds)

    def group_rest(self, cred, seconds, reason):
        self.rests[f"group:{cred.provider}:{cred.quota_group}"] = datetime.now(timezone.utc) + timedelta(seconds=seconds)
        self.health[cred.slot] = "resting"

    def custom_providers(self):
        return {}

    def pause_model(self, provider, model, why, detail):
        self.provider_overrides.setdefault(provider, {"models": {}}).setdefault("models", {})[model] = {"pause_reason": why}
        return [provider]

    def extra_models(self):
        return {}


def _locked(fn):
    """psycopg connections may be shared by the router's worker threads; serialise access."""
    @functools.wraps(fn)
    def inner(self, *a, **kw):
        with self._lock:
            return fn(self, *a, **kw)
    return inner


class DbUsageStore:
    def __init__(self, conn):
        self.conn = conn
        self._lock = threading.RLock()
        self._creds: dict[str, list[Credential]] = {}

    @_locked
    def requests_today(self, provider, model):
        row = db.one(self.conn, """select coalesce(sum(requests),0) n from provider_usage
                                   where service='llm' and provider=%s and model=%s
                                     and usage_date=(now() at time zone 'utc')::date""", (provider, model))
        return int(row["n"])

    @_locked
    def tokens_today(self, provider, model):
        row = db.one(self.conn, """select coalesce(sum(input_tokens+output_tokens),0) n from provider_usage
                                   where service='llm' and provider=%s and model=%s
                                     and usage_date=(now() at time zone 'utc')::date""", (provider, model))
        return int(row["n"])

    @_locked
    def record(self, provider, model, role, *, success, input_tokens, output_tokens, latency_ms, error, job_id=None,
               credential_id=None, cost_usd=0.0, cost_source="none"):
        db.run(self.conn, """insert into provider_usage (provider, model, service, role, job_id, input_tokens,
                              output_tokens, latency_ms, success, error, credential_id, cost_usd, cost_source)
                              values (%s,%s,'llm',%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
               (provider, model, role, job_id, input_tokens, output_tokens, latency_ms, success, error,
                credential_id, cost_usd, cost_source))
        if not success and error:
            db.run(self.conn, "update ai_providers set last_error=%s where name=%s", (error[:500], provider))

    @_locked
    def circuit_open(self, provider):
        row = db.one(self.conn, "select circuit_open_until from ai_providers where name=%s", (provider,))
        return bool(row and row["circuit_open_until"] and row["circuit_open_until"] > datetime.now(timezone.utc))

    @_locked
    def open_circuit(self, provider, seconds, reason):
        db.run(self.conn, """update ai_providers set circuit_open_until = now() + make_interval(secs => %s),
                             last_error=%s where name=%s""", (seconds, reason[:500], provider))

    @_locked
    def mark_success(self, provider):
        db.run(self.conn, """update ai_providers set circuit_open_until=null, last_success_at=now()
                             where name=%s""", (provider,))

    @_locked
    def pause_model(self, provider, model, why, detail):
        """Pause a model that is retired ('retired') or not free on this plan ('payment') on this provider and its other
        accounts (same address). It's re-tested on a schedule (studio.ai.health) and comes back by itself when it works.
        Returns the providers it was paused on."""
        from . import health

        rows = db.all_(self.conn, """update ai_model_configs
                                        set pause_reason = %s, paused_at = now(), checks = 0, pause_detail = %s,
                                            next_check_at = now() + make_interval(secs => %s)
                                      where model = %s and pause_reason is null and provider in (
                                        select name from ai_providers
                                         where base_url = (select base_url from ai_providers where name = %s))
                                     returning provider""",
                       (why, detail[:300], health.SCHEDULE[why][0], model, provider))
        names = sorted({r["provider"] for r in rows}) or [provider]
        if rows:
            db.run(self.conn, "insert into audit_logs (actor, action, target_type, target_id, details) values "
                              "('engine','ai_model_paused','ai_model',%s,%s)",
                   (model, db.j({"providers": names, "reason": why, "detail": detail[:300]})))
            if why == "retired":  # a lasting change the owner should know about now; a paid model only after a week
                from .. import config, notify

                notify.send(self.conn, "ai_model_retired", f"AI model switched off: {model}",
                            f"{', '.join(names)} says this model is no longer available ({detail[:160]}). The studio stopped "
                            "using it and re-tests it once a week for 4 weeks. Other models take over its jobs.",
                            link=f"{config.runtime().dashboard_url}/settings/ai", dedupe_key=f"retired:{provider}:{model}")
        return names

    @_locked
    def error_rate(self, provider, model):
        row = db.one(self.conn, """select avg(case when success then 0 else 1 end)::float r from (
                                     select success from provider_usage where service='llm' and provider=%s
                                       and model=%s and coalesce(error,'') not like '%% auth'
                                     order by id desc limit 20) t""", (provider, model))
        return float(row["r"] or 0.0)

    @_locked
    def overrides(self):
        rows = db.all_(self.conn, "select name, enabled from ai_providers")
        models = db.all_(self.conn, """select provider, model, enabled, daily_request_limit, priority, pause_reason
                                          from ai_model_configs""")
        out: dict[str, dict] = {r["name"]: {"enabled": r["enabled"], "models": {}} for r in rows}
        for m in models:
            out.setdefault(m["provider"], {"models": {}})["models"][m["model"]] = m
        catalog = db.get_setting(self.conn, "model_catalog", {}) or {}
        for name, info in (catalog.get("providers") or {}).items():
            out.setdefault(name, {"models": {}})["missing"] = info.get("missing") or {}
        for m in db.all_(self.conn, "select provider, model, roles from ai_model_configs where roles_custom"):
            out.setdefault(m["provider"], {"models": {}}).setdefault("roles", {})[m["model"]] = list(m["roles"] or [])
        return out

    # credentials ---------------------------------------------------------------
    @_locked
    def credential_rows(self, provider):
        if provider not in self._creds:
            from .. import oauth

            rows = db.all_(self.conn, """select c.*, s.ciphertext from ai_credentials c
                                          join ai_credential_secrets s on s.credential_id = c.id
                                         where c.provider=%s and c.enabled order by c.priority, c.label""", (provider,))
            out = []
            for r in rows:
                try:
                    key = oauth.decrypt(r["ciphertext"]).get("key")
                except Exception:  # wrong TOKEN_ENCRYPTION_KEY or corrupted row: never use, report it
                    db.run(self.conn, """update ai_credentials set health='invalid', last_error='Could not decrypt this key;
                                          replace it in the AI API Manager', last_error_at=now() where id=%s""", (r["id"],))
                    continue
                out.append(Credential(str(r["id"]), provider, r["label"], key, priority=r["priority"], weight=r["weight"],
                                      quota_group=r["quota_group"], daily_request_cap=r["daily_request_cap"],
                                      daily_token_cap=r["daily_token_cap"],
                                      monthly_spend_cap_usd=r["monthly_spend_cap_usd"],
                                      input_usd_per_mtok=r["input_usd_per_mtok"],
                                      output_usd_per_mtok=r["output_usd_per_mtok"],
                                      max_concurrency=r["max_concurrency"],
                                      consecutive_failures=r["consecutive_failures"]))
            self._creds[provider] = out
        return self._creds[provider]

    @_locked
    def provider_settings(self, provider):
        row = db.one(self.conn, """select key_strategy, max_concurrency, request_timeout_s, max_retries, use_env_key
                                     from ai_providers where name=%s""", (provider,))
        return ProviderSettings(**row) if row else ProviderSettings()

    def _rests(self) -> dict:
        return db.get_setting(self.conn, "ai_quota_rests", {}) or {}

    @_locked
    def credential_resting(self, cred, now):
        group_until = self._rests().get(f"{cred.provider}:{cred.quota_group}")
        if group_until and datetime.fromisoformat(group_until) > now:
            return True
        if cred.id is None:
            return False
        row = db.one(self.conn, "select circuit_open_until from ai_credentials where id=%s", (cred.id,))
        return bool(row and row["circuit_open_until"] and row["circuit_open_until"] > now)

    @_locked
    def credential_usage(self, cred):
        where, args = ("credential_id=%s", (cred.id,)) if cred.id else ("credential_id is null and provider=%s", (cred.provider,))
        row = db.one(self.conn, f"""
            select coalesce(sum(requests) filter (where usage_date=(now() at time zone 'utc')::date),0) req,
                   coalesce(sum(input_tokens+output_tokens) filter (where usage_date=(now() at time zone 'utc')::date),0) tok,
                   coalesce(sum(cost_usd) filter (where created_at >= %s),0) cost
              from provider_usage where service='llm' and {where}""", (utc_month_start(),) + args)
        err = db.one(self.conn, f"""select avg(case when success then 0 else 1 end)::float r from (
                                      select success from provider_usage where service='llm' and {where}
                                       order by id desc limit 20) t""", args)
        return {"requests_today": int(row["req"]), "tokens_today": int(row["tok"]), "cost_month": float(row["cost"]),
                "error_rate": float(err["r"] or 0.0)}

    @_locked
    def credential_health(self, cred, health, rest_seconds, error, reset=False):
        if cred.id is None:
            if reset:
                self._clear_group(cred)
            return
        if reset:
            db.run(self.conn, """update ai_credentials set health='healthy', consecutive_failures=0, circuit_open_until=null,
                                  last_success_at=now() where id=%s""", (cred.id,))
            self._clear_group(cred)
            return
        if health == "invalid":
            from .. import config, notify

            notify.send(self.conn, "ai_key_rejected", f"AI key rejected: {cred.label} ({cred.provider})",
                        "The provider refused this key. Press Replace on it in Settings → AI keys and paste a new one. "
                        "Until then the studio uses its other keys and services.",
                        link=f"{config.runtime().dashboard_url}/settings/ai",
                        dedupe_key=f"keyrejected:{cred.id}:{datetime.now(timezone.utc):%Y%m%d}")
        db.run(self.conn, """update ai_credentials set health=%s, consecutive_failures=consecutive_failures+1,
                              circuit_open_until=case when %s::int is null then circuit_open_until
                                                      else now() + make_interval(secs => %s::int) end,
                              last_error=coalesce(%s, last_error), last_error_at=now() where id=%s""",
               (health, rest_seconds, rest_seconds, (error or "")[:500] or None, cred.id))

    def _clear_group(self, cred):
        rests = self._rests()
        if rests.pop(f"{cred.provider}:{cred.quota_group}", None) is not None:
            db.set_setting(self.conn, "ai_quota_rests", rests)

    @_locked
    def group_rest(self, cred, seconds, reason):
        rests = self._rests()
        rests[f"{cred.provider}:{cred.quota_group}"] = (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat()
        db.set_setting(self.conn, "ai_quota_rests", rests)
        db.run(self.conn, """update ai_credentials set health='resting', last_error=%s, last_error_at=now()
                              where provider=%s and quota_group=%s""", (reason[:500], cred.provider, cred.quota_group))

    @_locked
    def extra_models(self):
        """Models added in the AI API Manager to a built-in provider: {provider: [model, ...]}."""
        rows = db.all_(self.conn, """select m.provider, m.model, m.roles, m.daily_request_limit, m.priority
                                      from ai_model_configs m join ai_providers p on p.name = m.provider
                                     where p.key_env is not null and m.enabled""")
        out: dict[str, list[dict]] = {}
        for m in rows:
            roles = list(m["roles"] or [])
            out.setdefault(m["provider"], []).append(
                {"id": m["model"], "roles": roles, "daily_requests": m["daily_request_limit"], "priority": m["priority"] or 100,
                 "kind": "embeddings" if roles == ["embeddings"] else "chat"})
        return out

    def custom_providers(self):
        """Providers added in the AI API Manager (not in providers.yaml), with their models."""
        rows = db.all_(self.conn, "select name, enabled, base_url, commercial_use_ok from ai_providers where key_env is null")
        out = {}
        for r in rows:
            models = db.all_(self.conn, """select model, roles, daily_request_limit, priority from ai_model_configs
                                           where provider=%s and enabled""", (r["name"],))
            out[r["name"]] = {"enabled": r["enabled"], "base_url": r["base_url"], "key_env": None, "custom": True,
                              "commercial_use": "assumed" if r["commercial_use_ok"] else "no",
                              "models": [{"id": m["model"], "roles": list(m["roles"] or []),
                                          "daily_requests": m["daily_request_limit"], "priority": m["priority"] or 100}
                                         for m in models]}
        return out


class ProbeStore(DbUsageStore):
    """For tests of a model (key check, scheduled re-tests): each model is judged on its own. One failing model doesn't
    rest its provider or key for the others, a resting provider or key is still tried, and pausing is left to the caller."""

    def open_circuit(self, *a, **k):
        return None

    def group_rest(self, *a, **k):
        return None

    def circuit_open(self, *a, **k):
        return False

    def credential_resting(self, *a, **k):
        return False

    def pause_model(self, *a, **k):
        return []
