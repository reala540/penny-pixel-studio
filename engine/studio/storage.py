"""Supabase Storage (private bucket 'studio') with a local-folder fallback for tests/offline runs."""

from __future__ import annotations

import mimetypes
import shutil
from pathlib import Path

import httpx

from . import config
from .errors import AuthError, TransientError

BUCKET = "studio"


class SupabaseStorage:
    def __init__(self, url: str, service_key: str, client: httpx.Client | None = None):
        self.base = url.rstrip("/") + "/storage/v1"
        self.headers = {"Authorization": f"Bearer {service_key}", "apikey": service_key}
        self.client = client or httpx.Client(timeout=httpx.Timeout(300.0, connect=20.0))

    def upload(self, key: str, local: Path, content_type: str | None = None) -> str:
        ctype = content_type or mimetypes.guess_type(local.name)[0] or "application/octet-stream"
        with local.open("rb") as fh:
            r = self.client.post(f"{self.base}/object/{BUCKET}/{key}", content=fh.read(),
                                 headers={**self.headers, "Content-Type": ctype, "x-upsert": "true"})
        self._check(r)
        return key

    def download(self, key: str, local: Path) -> Path:
        r = self.client.get(f"{self.base}/object/{BUCKET}/{key}", headers=self.headers)
        self._check(r)
        local.parent.mkdir(parents=True, exist_ok=True)
        local.write_bytes(r.content)
        return local

    def delete(self, keys: list[str]) -> None:
        if not keys:
            return
        r = self.client.request("DELETE", f"{self.base}/object/{BUCKET}", json={"prefixes": keys},
                                headers=self.headers)
        self._check(r)

    @staticmethod
    def _check(r: httpx.Response) -> None:
        if r.status_code in (401, 403):
            raise AuthError(f"Storage rejected the service key ({r.status_code})")
        if r.status_code >= 400:
            raise TransientError(f"Storage error {r.status_code}: {r.text[:200]}")


class LocalStorage:
    """Stores files under .work/storage — used by tests and `studio demo`."""

    def __init__(self, root: Path | None = None):
        self.root = root or (config.runtime().work_dir / "storage")
        self.root.mkdir(parents=True, exist_ok=True)

    def upload(self, key: str, local: Path, content_type: str | None = None) -> str:
        target = self.root / key
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(local, target)
        return key

    def download(self, key: str, local: Path) -> Path:
        local.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(self.root / key, local)
        return local

    def delete(self, keys: list[str]) -> None:
        for k in keys:
            (self.root / k).unlink(missing_ok=True)


def default_storage():
    rt = config.runtime()
    if rt.supabase_url and rt.supabase_service_key:
        return SupabaseStorage(rt.supabase_url, rt.supabase_service_key)
    return LocalStorage()
