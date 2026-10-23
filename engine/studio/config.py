"""Configuration: YAML files in /config plus environment variables (secrets)."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]


def config_dir() -> Path:
    return Path(os.environ.get("STUDIO_CONFIG_DIR", REPO_ROOT / "config"))


def _expand_env(value: Any) -> Any:
    if isinstance(value, str):
        return re.sub(r"\$\{(\w+)\}", lambda m: os.environ.get(m.group(1), ""), value)
    if isinstance(value, dict):
        return {k: _expand_env(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_expand_env(v) for v in value]
    return value


@lru_cache(maxsize=None)
def load_yaml(name: str) -> dict:
    path = config_dir() / name
    with path.open() as fh:
        return yaml.safe_load(fh) or {}


def brand() -> dict:
    return load_yaml("brand.yaml")


def accounts() -> dict:
    return load_yaml("accounts.yaml")


def providers() -> dict:
    return _expand_env(load_yaml("providers.yaml"))


def research() -> dict:
    return load_yaml("research.yaml")


def services() -> dict:
    return load_yaml("services.yaml")


def env(name: str, default: str | None = None) -> str | None:
    value = os.environ.get(name)
    return value if value not in (None, "") else default


@dataclass
class Runtime:
    db_url: str | None = field(default_factory=lambda: env("SUPABASE_DB_URL"))
    supabase_url: str | None = field(default_factory=lambda: env("SUPABASE_URL"))
    supabase_service_key: str | None = field(default_factory=lambda: env("SUPABASE_SERVICE_ROLE_KEY"))
    token_key: str | None = field(default_factory=lambda: env("TOKEN_ENCRYPTION_KEY"))
    telegram_token: str | None = field(default_factory=lambda: env("TELEGRAM_BOT_TOKEN"))
    telegram_chat_id: str | None = field(default_factory=lambda: env("TELEGRAM_CHAT_ID"))
    dashboard_url: str = field(default_factory=lambda: env("DASHBOARD_URL", "http://localhost:5173") or "")
    work_dir: Path = field(default_factory=lambda: Path(env("STUDIO_WORK_DIR", str(REPO_ROOT / ".work")) or ".work"))
    cache_dir: Path = field(
        default_factory=lambda: Path(env("STUDIO_CACHE_DIR", str(Path.home() / ".cache" / "studio")) or ".cache")
    )

    def require_db(self) -> str:
        if not self.db_url:
            raise SystemExit("SUPABASE_DB_URL is not set. See GUIDE.md step 4.")
        return self.db_url


def runtime() -> Runtime:
    rt = Runtime()
    rt.work_dir.mkdir(parents=True, exist_ok=True)
    rt.cache_dir.mkdir(parents=True, exist_ok=True)
    return rt
