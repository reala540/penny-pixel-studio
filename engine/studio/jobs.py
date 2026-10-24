"""Persistent, idempotent job runner. The database row is the source of truth.

Every pipeline stage runs through `run_stage`, which:
  * creates (or finds) the job row by idempotency key,
  * returns the stored output if that stage already completed (safe resume),
  * records each attempt, classifies errors, and schedules retries with backoff + jitter,
  * never retries auth/permanent/validation errors automatically.
"""

from __future__ import annotations

import random
import time
import traceback
from contextvars import ContextVar
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from . import db
from .errors import NeedsReview, StudioError

BACKOFF_BASE_SECONDS = 60

# Context-local so concurrent runners never attribute one job's model calls to another.
active_job_id: ContextVar[object | None] = ContextVar("studio_active_job_id", default=None)


@contextmanager
def job_context(job_id):
    token = active_job_id.set(job_id)
    try:
        yield
    finally:
        active_job_id.reset(token)


def progress(conn, label: str, step: int | None = None, total: int | None = None) -> None:
    """Show what the current job is doing on the Activity page. Best effort; a failure never stops the work."""
    job_id = active_job_id.get()
    if job_id is None:
        return
    try:
        db.run(conn, "update generation_jobs set progress=%s, updated_at=now() where id=%s",
               (db.j({"label": label[:200], "step": step, "total": total}), job_id))
    except Exception:
        pass


@contextmanager
def tracked_run(conn, job_type: str, key: str, input: dict | None = None):
    """Record a scheduled run (weekly research, production, publishing) as a job, so it shows as running."""
    row = db.one(conn, """insert into generation_jobs (job_type, idempotency_key, status, requested_by, input, started_at, attempts)
                          values (%s,%s,'running','system',%s,now(),1)
                          on conflict (idempotency_key) do update set status='running', started_at=now(),
                                 attempts=generation_jobs.attempts+1
                          returning id""", (job_type, key, db.j(input or {})))
    holder: dict = {}
    try:
        with job_context(row["id"]):
            yield holder
    except BaseException as exc:
        db.run(conn, "update generation_jobs set status='failed', error_message=%s, finished_at=now(), progress=null where id=%s",
               (str(exc)[:1000], row["id"]))
        raise
    db.run(conn, "update generation_jobs set status='completed', output=%s, finished_at=now(), progress=null where id=%s",
           (db.j(holder.get("output") or {}), row["id"]))


def _now() -> datetime:
    return datetime.now(timezone.utc)


def backoff_delay(attempt: int, base: int = BACKOFF_BASE_SECONDS) -> float:
    """Exponential backoff with full jitter, capped at 6 hours."""
    cap = min(base * (2 ** max(attempt - 1, 0)), 6 * 3600)
    return random.uniform(cap / 2, cap)


def ensure_job(conn, job_type: str, key: str, *, project_id=None, parent_job_id=None,
               input: dict | None = None, requested_by: str = "system", max_attempts: int = 3) -> dict:
    row = db.one(conn, """
        insert into generation_jobs (job_type, idempotency_key, project_id, parent_job_id, input,
                                     requested_by, max_attempts, status)
        values (%s,%s,%s,%s,%s,%s,%s,'pending')
        on conflict (idempotency_key) do nothing
        returning *""", (job_type, key, project_id, parent_job_id, db.j(input or {}), requested_by, max_attempts))
    if row is None:
        row = db.one(conn, "select * from generation_jobs where idempotency_key = %s", (key,))
    return row


class StageResult:
    def __init__(self, status: str, output: dict, job: dict):
        self.status = status
        self.output = output
        self.job = job

    @property
    def ok(self) -> bool:
        return self.status == "completed"


def run_stage(conn, job_type: str, key: str, fn: Callable[[dict], dict], *, project_id=None,
              parent_job_id=None, input: dict | None = None, requested_by: str = "system",
              max_attempts: int = 3) -> StageResult:
    job = ensure_job(conn, job_type, key, project_id=project_id, parent_job_id=parent_job_id,
                     input=input, requested_by=requested_by, max_attempts=max_attempts)
    if job["status"] == "completed":
        return StageResult("completed", job["output"], job)
    if job["status"] in ("cancelled", "expired"):
        return StageResult(job["status"], job["output"], job)
    if job["status"] == "retrying" and job["next_attempt_at"] and job["next_attempt_at"] > _now():
        return StageResult("retrying", job["output"], job)

    attempt = job["attempts"] + 1
    claimed = db.one(conn, """
        update generation_jobs set status='running', attempts=%s, started_at=now(), error_kind=null,
               error_message=null
         where id=%s and status not in ('running','completed','cancelled')
        returning *""", (attempt, job["id"]))
    if claimed is None:  # someone else is running it
        job = db.one(conn, "select * from generation_jobs where id=%s", (job["id"],))
        return StageResult(job["status"], job["output"], job)
    attempt_row = db.one(conn, "insert into job_attempts (job_id, attempt, status) values (%s,%s,'running') returning id",
                         (job["id"], attempt))
    started = time.monotonic()
    try:
        with job_context(claimed["id"]):
            output = fn(dict(claimed["input"] or {})) or {}
    except NeedsReview as exc:
        return _finish(conn, claimed, attempt_row["id"], "needs_review", {}, exc, started)
    except StudioError as exc:
        if exc.retryable and attempt < claimed["max_attempts"]:
            return _finish(conn, claimed, attempt_row["id"], "retrying", {}, exc, started,
                           next_at=_now() + timedelta(seconds=backoff_delay(attempt)))
        status = "blocked" if exc.kind in ("auth", "quota") else "failed"
        return _finish(conn, claimed, attempt_row["id"], status, {}, exc, started)
    except Exception as exc:  # unknown bug: treat as transient once, then fail
        if attempt < min(2, claimed["max_attempts"]):
            return _finish(conn, claimed, attempt_row["id"], "retrying", {}, exc, started,
                           next_at=_now() + timedelta(seconds=backoff_delay(attempt)))
        return _finish(conn, claimed, attempt_row["id"], "failed", {}, exc, started)
    return _finish(conn, claimed, attempt_row["id"], "completed", output, None, started)


def _finish(conn, job, attempt_id, status, output, exc, started, next_at=None) -> StageResult:
    kind = getattr(exc, "kind", "unknown") if exc else None
    message = (str(exc) or exc.__class__.__name__)[:2000] if exc else None
    log = None
    if exc is not None and not isinstance(exc, StudioError):
        log = "".join(traceback.format_exception(exc))[-4000:]
    db.run(conn, """update job_attempts set status=%s, error_kind=%s, error_message=%s, log_excerpt=%s,
                    finished_at=now() where id=%s""", (status, kind, message, log, attempt_id))
    row = db.one(conn, """
        update generation_jobs set status=%s, output=%s, error_kind=%s, error_message=%s,
               next_attempt_at=%s, finished_at=case when %s in ('completed','failed','blocked','needs_review') then now() end
         where id=%s returning *""",
        (status, db.j(output), kind, message, next_at, status, job["id"]))
    elapsed = time.monotonic() - started
    db.run(conn, """insert into provider_usage (provider, service, job_id, units, latency_ms, success, error)
                    values ('github_actions','compute',%s,0,%s,%s,%s)""",
           (job["id"], int(elapsed * 1000), status == "completed", message))
    return StageResult(status, output, row)


def due_jobs(conn, limit: int = 20) -> list[dict]:
    """Owner-requested or retrying jobs that are ready to run now."""
    return db.all_(conn, """
        select * from generation_jobs
         where (status = 'queued') or (status = 'retrying' and coalesce(next_attempt_at, now()) <= now())
         order by created_at limit %s""", (limit,))


def reset_stale_running(conn, older_than_minutes: int = 120) -> int:
    """A crashed runner leaves jobs 'running'. Put them back so they can resume."""
    return db.run(conn, """
        update generation_jobs set status='retrying', next_attempt_at=now(),
               error_message='Runner stopped unexpectedly; resuming'
         where status='running' and started_at < now() - make_interval(mins => %s)
           and job_type not in ('weekly_research', 'weekly_production')""", (older_than_minutes,))
