"""Several authorized API keys per provider: selection strategies, limits, health and concurrency.

A provider's GitHub-secret key (``key_env``) is one credential; keys added in the AI API Manager are more.
Each credential has its own caps (requests/day, tokens/day, estimated spend/month) and health.

Rate limits are treated as shared by every credential in the same *quota group*. By default a credential's
group is its provider, so when one key is throttled its siblings rest too and the router moves to another
provider: keys are never rotated to get around a provider's quota. Only a key the owner attests belongs to a
separate account (with its own allowance, used within that account's terms) gets its own group.
"""

from __future__ import annotations

import random
import threading
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Iterator

STRATEGIES = ("round_robin", "priority", "least_utilized", "health", "weighted")
ENV_LABEL = "GitHub secret"


@dataclass
class Credential:
    id: str | None                      # None = the provider's GitHub-secret key
    provider: str
    label: str
    key: str | None
    priority: int = 100
    weight: int = 1
    quota_group: str = ""
    daily_request_cap: int | None = None
    daily_token_cap: int | None = None
    monthly_spend_cap_usd: float | None = None
    input_usd_per_mtok: float | None = None
    output_usd_per_mtok: float | None = None
    max_concurrency: int = 2
    consecutive_failures: int = 0

    def __post_init__(self):
        self.quota_group = self.quota_group or self.provider

    @property
    def slot(self) -> str:
        return self.id or f"env:{self.provider}"

    def estimate_cost(self, input_tokens: int, output_tokens: int) -> tuple[float, str]:
        if self.input_usd_per_mtok is None and self.output_usd_per_mtok is None:
            return 0.0, "none"
        cost = (input_tokens / 1e6) * float(self.input_usd_per_mtok or 0) + \
               (output_tokens / 1e6) * float(self.output_usd_per_mtok or 0)
        return round(cost, 6), "estimated"


@dataclass
class ProviderSettings:
    key_strategy: str = "priority"
    max_concurrency: int = 2
    request_timeout_s: int = 120
    max_retries: int = 2
    use_env_key: bool = True


def backoff_seconds(attempt: int, base: float = 0.5, cap: float = 20.0, rng: random.Random | None = None) -> float:
    """Exponential backoff with full jitter: random in [0, min(cap, base * 2**attempt)]."""
    return (rng or random).uniform(0, min(cap, base * (2 ** attempt)))


@dataclass
class CredentialPool:
    """Chooses credentials for a provider. `store` supplies credential rows, usage and health persistence."""

    store: object
    _rr: dict[str, int] = field(default_factory=dict)
    _sems: dict[str, threading.BoundedSemaphore] = field(default_factory=dict)
    _inflight: dict[str, int] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    # ------------------------------------------------------------------ discovery
    def credentials(self, provider: str, provider_cfg: dict, settings: ProviderSettings, env_key: str | None) -> list[Credential]:
        creds: list[Credential] = []
        if env_key and settings.use_env_key:
            creds.append(Credential(None, provider, ENV_LABEL, env_key, priority=int(provider_cfg.get("env_key_priority", 50)),
                                    max_concurrency=settings.max_concurrency))
        creds.extend(self.store.credential_rows(provider))
        return creds

    def eligible(self, creds: list[Credential]) -> list[Credential]:
        out = []
        now = datetime.now(timezone.utc)
        for c in creds:
            if not c.key:
                continue
            if self.store.credential_resting(c, now):
                continue
            used = self.store.credential_usage(c)
            if c.daily_request_cap is not None and used["requests_today"] >= c.daily_request_cap:
                continue
            if c.daily_token_cap is not None and used["tokens_today"] >= c.daily_token_cap:
                continue
            if c.monthly_spend_cap_usd is not None and used["cost_month"] >= float(c.monthly_spend_cap_usd):
                continue
            if c.weight == 0 and len(creds) > 1:
                continue
            out.append(c)
        return out

    # ------------------------------------------------------------------ strategies
    def order(self, provider: str, creds: list[Credential], strategy: str) -> list[Credential]:
        if len(creds) <= 1:
            return list(creds)
        strategy = strategy if strategy in STRATEGIES else "priority"
        usage = {c.slot: self.store.credential_usage(c) for c in creds}
        if strategy == "priority":
            return sorted(creds, key=lambda c: (c.priority, c.label))
        if strategy == "round_robin":
            ordered = sorted(creds, key=lambda c: (c.priority, c.label))
            with self._lock:
                start = self._rr.get(provider)
                if start is None:  # continue the rotation across runs from today's measured traffic
                    start = sum(u["requests_today"] for u in usage.values())
                self._rr[provider] = start + 1
            k = start % len(ordered)
            return ordered[k:] + ordered[:k]
        if strategy == "least_utilized":
            def used_share(c):
                u = usage[c.slot]
                shares = []
                if c.daily_request_cap:
                    shares.append(u["requests_today"] / c.daily_request_cap)
                if c.daily_token_cap:
                    shares.append(u["tokens_today"] / c.daily_token_cap)
                if c.monthly_spend_cap_usd:
                    shares.append(u["cost_month"] / float(c.monthly_spend_cap_usd))
                # without caps, compare raw traffic on a common scale
                return max(shares) if shares else u["requests_today"] / 10_000
            return sorted(creds, key=lambda c: (used_share(c), c.priority))
        if strategy == "health":
            return sorted(creds, key=lambda c: (usage[c.slot]["error_rate"], c.consecutive_failures, c.priority))
        # weighted: send the next request to whoever is furthest below its share
        with self._lock:
            inflight = dict(self._inflight)
        return sorted(creds, key=lambda c: ((usage[c.slot]["requests_today"] + inflight.get(c.slot, 0)) / max(c.weight, 1),
                                            -c.weight, c.priority))

    # ------------------------------------------------------------------ concurrency
    @contextmanager
    def slot(self, cred: Credential, wait_s: float = 0.0) -> Iterator[bool]:
        with self._lock:
            sem = self._sems.get(cred.slot)
            if sem is None:
                sem = self._sems[cred.slot] = threading.BoundedSemaphore(max(1, cred.max_concurrency))
        got = sem.acquire(timeout=wait_s) if wait_s > 0 else sem.acquire(blocking=False)
        if got:
            with self._lock:
                self._inflight[cred.slot] = self._inflight.get(cred.slot, 0) + 1
        try:
            yield got
        finally:
            if got:
                with self._lock:
                    self._inflight[cred.slot] -= 1
                sem.release()

    # ------------------------------------------------------------------ health
    def report(self, cred: Credential, outcome: str, *, retry_after: int | None = None, error: str | None = None) -> None:
        """outcome: success | transient | rate_limited | auth | payment."""
        if outcome == "success":
            cred.consecutive_failures = 0
            self.store.credential_health(cred, "healthy", None, None, reset=True)
            return
        cred.consecutive_failures += 1
        if outcome == "transient":
            rest = 120 if cred.consecutive_failures >= 3 else None
            self.store.credential_health(cred, "degraded" if rest is None else "resting", rest, error)
        elif outcome == "rate_limited":
            secs = min(max(int(retry_after or 900), 30), 6 * 3600)
            self.store.group_rest(cred, secs, error or "rate limited")
        elif outcome == "auth":
            self.store.credential_health(cred, "invalid", 24 * 3600, error or "key rejected")
        elif outcome == "payment":
            self.store.credential_health(cred, "exhausted", 24 * 3600, error or "payment required")


def utc_month_start(now: datetime | None = None) -> datetime:
    now = now or datetime.now(timezone.utc)
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def mask(key: str) -> str:
    """Only the last 4 characters are ever shown."""
    return "••••" + key[-4:] if len(key) >= 8 else "••••"


def rest_until(seconds: int) -> datetime:
    return datetime.now(timezone.utc) + timedelta(seconds=seconds)
