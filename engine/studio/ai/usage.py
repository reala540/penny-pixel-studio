"""Usage + health tracking for AI providers (per-day request/token counts, circuit breakers)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Protocol

from .. import db


class UsageStore(Protocol):
    def requests_today(self, provider: str, model: str) -> int: ...
    def tokens_today(self, provider: str, model: str) -> int: ...
    def record(self, provider: str, model: str, role: str, *, success: bool, input_tokens: int,
               output_tokens: int, latency_ms: int, error: str | None, job_id=None) -> None: ...
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

    def _today(self, provider, model):
        today = date.today()
        return [c for c in self.calls if c["provider"] == provider and c["model"] == model and c["day"] == today]

    def requests_today(self, provider, model):
        return len(self._today(provider, model))

    def tokens_today(self, provider, model):
        return sum(c["in"] + c["out"] for c in self._today(provider, model))

    def record(self, provider, model, role, *, success, input_tokens, output_tokens, latency_ms, error, job_id=None):
        self.calls.append({"provider": provider, "model": model, "role": role, "success": success,
                           "in": input_tokens, "out": output_tokens, "day": date.today(), "error": error})

    def circuit_open(self, provider):
        until = self.circuits.get(provider)
        return bool(until and until > datetime.now(timezone.utc))

    def open_circuit(self, provider, seconds, reason):
        self.circuits[provider] = datetime.now(timezone.utc) + timedelta(seconds=seconds)

    def mark_success(self, provider):
        self.circuits.pop(provider, None)

    def error_rate(self, provider, model):
        recent = [c for c in self.calls if c["provider"] == provider and c["model"] == model][-20:]
        if not recent:
            return 0.0
        return sum(1 for c in recent if not c["success"]) / len(recent)

    def overrides(self):
        return self.provider_overrides


class DbUsageStore:
    def __init__(self, conn):
        self.conn = conn

    def requests_today(self, provider, model):
        row = db.one(self.conn, """select coalesce(sum(requests),0) n from provider_usage
                                   where service='llm' and provider=%s and model=%s
                                     and usage_date=(now() at time zone 'utc')::date""", (provider, model))
        return int(row["n"])

    def tokens_today(self, provider, model):
        row = db.one(self.conn, """select coalesce(sum(input_tokens+output_tokens),0) n from provider_usage
                                   where service='llm' and provider=%s and model=%s
                                     and usage_date=(now() at time zone 'utc')::date""", (provider, model))
        return int(row["n"])

    def record(self, provider, model, role, *, success, input_tokens, output_tokens, latency_ms, error, job_id=None):
        db.run(self.conn, """insert into provider_usage (provider, model, service, role, job_id, input_tokens,
                              output_tokens, latency_ms, success, error)
                              values (%s,%s,'llm',%s,%s,%s,%s,%s,%s,%s)""",
               (provider, model, role, job_id, input_tokens, output_tokens, latency_ms, success, error))
        if not success and error:
            db.run(self.conn, "update ai_providers set last_error=%s where name=%s", (error[:500], provider))

    def circuit_open(self, provider):
        row = db.one(self.conn, "select circuit_open_until from ai_providers where name=%s", (provider,))
        return bool(row and row["circuit_open_until"] and row["circuit_open_until"] > datetime.now(timezone.utc))

    def open_circuit(self, provider, seconds, reason):
        db.run(self.conn, """update ai_providers set circuit_open_until = now() + make_interval(secs => %s),
                             last_error=%s where name=%s""", (seconds, reason[:500], provider))

    def mark_success(self, provider):
        db.run(self.conn, """update ai_providers set circuit_open_until=null, last_success_at=now()
                             where name=%s""", (provider,))

    def error_rate(self, provider, model):
        row = db.one(self.conn, """select avg(case when success then 0 else 1 end)::float r from (
                                     select success from provider_usage where service='llm' and provider=%s
                                       and model=%s order by id desc limit 20) t""", (provider, model))
        return float(row["r"] or 0.0)

    def overrides(self):
        rows = db.all_(self.conn, "select name, enabled from ai_providers")
        models = db.all_(self.conn, "select provider, model, enabled, daily_request_limit, priority from ai_model_configs")
        out: dict[str, dict] = {r["name"]: {"enabled": r["enabled"], "models": {}} for r in rows}
        for m in models:
            out.setdefault(m["provider"], {"models": {}})["models"][m["model"]] = m
        return out
