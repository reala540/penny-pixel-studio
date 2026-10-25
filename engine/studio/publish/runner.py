"""Publishes due, approved posts — safely.

Safeguards (each is tested):
  * only explicitly approved variants with an approval record are published;
  * the post's account must match the variant's account;
  * a post that already has a published_posts row is never sent again;
  * the exact same video or text (by SHA-256 fingerprint) is never sent to the same account twice, enforced by a
    unique index in the database as well as here;
  * an attempt is recorded before anything is sent; an attempt that never finished or ended unclear blocks that post
    until the owner confirms it isn't on the platform;
  * expired time-sensitive content is blocked until rechecked;
  * media without license records is blocked;
  * ambiguous failures go to human review, never blind retry;
  * when an API can't publish, a manual task with instructions is created instead.
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import psycopg

from .. import config, db, notify, oauth
from ..errors import AmbiguousPublish, AuthError, BudgetExceeded, PermanentError, QuotaError, StudioError, TransientError
from ..media import render as rendering
from .adapters import ADAPTERS

MAX_ATTEMPTS = 3
LOCK_MINUTES = 45


def claim_due(conn, limit: int = 10, now: datetime | None = None) -> list[dict]:
    """Atomically claim due posts (skip-locked) so two runners can never publish the same post."""
    return db.all_(conn, """
        update scheduled_posts sp set status='publishing', attempts=attempts+1,
               locked_until=now() + make_interval(mins => %s)
         where sp.id in (select id from scheduled_posts
                          where status='scheduled' and scheduled_at <= coalesce(%s, now())
                            and (locked_until is null or locked_until < now())
                          order by scheduled_at limit %s for update skip locked)
        returning sp.*""", (LOCK_MINUTES, now, limit))


def _context(conn, post: dict) -> dict:
    return db.one(conn, """
        select v.*, v.status variant_status, a.platform, a.label account_label, a.enabled account_enabled,
               a.external_id, p.id project_id, p.status project_status, p.fresh_until, p.recipe, p.format,
               p.channel_slug, p.title project_title, p.current_script_version_id
          from content_variants v join social_accounts a on a.id=v.social_account_id
          join content_projects p on p.id=v.project_id where v.id=%s""", (post["variant_id"],))


def safety_problems(conn, post: dict, ctx: dict, now: datetime) -> list[str]:
    problems = []
    if db.get_setting(conn, "paused", False):
        problems.append("paused")
    if ctx is None:
        return ["variant missing"]
    if ctx["social_account_id"] != post["social_account_id"]:
        problems.append("account mismatch between post and variant")
    if not ctx["account_enabled"]:
        problems.append("account disabled")
    if ctx["variant_status"] != "approved":
        problems.append("variant not approved")
    approval = db.one(conn, """select 1 from approvals where decision='approved'
                               and ((target_type='variant' and target_id=%s) or (target_type='project' and target_id=%s))
                               limit 1""", (ctx["id"], ctx["project_id"]))
    if not approval:
        problems.append("no explicit approval record")
    if ctx["fresh_until"] and ctx["fresh_until"] < now:
        problems.append("content expired: time-sensitive facts must be rechecked")
    for sc in ((ctx["recipe"] or {}).get("render") or {}).get("scenes", []):
        if sc.get("photo_key") and not sc.get("license_record_id"):
            problems.append("media without license record")
            break
    return problems


def _manual(conn, post, ctx, reason: str, status: str = "needs_manual", storage=None) -> None:
    dash = config.runtime().dashboard_url
    asset_key = None
    if storage is not None and ctx["kind"] != "text_post":
        try:  # give the owner the final-quality file to upload by hand
            video, _ = final_media(conn, storage, ctx)
            if video:
                asset_key = storage.upload(f"manual/{post['id']}.mp4", video, "video/mp4")
                db.run(conn, """insert into media_assets (project_id, kind, storage_path, bytes, expires_at)
                                values (%s,'final_video',%s,%s, now() + interval '14 days')""",
                       (ctx["project_id"], asset_key, video.stat().st_size))
        except Exception:
            asset_key = None
    db.run(conn, """insert into manual_tasks (scheduled_post_id, platform, title, instructions, deep_link, asset_key)
                    values (%s,%s,%s,%s,%s,%s)""",
           (post["id"], ctx["platform"], f"Post manually: {ctx.get('title') or ctx['project_title']}",
            f"{reason}. Download the file, copy the caption from the dashboard, post it yourself, then press "
            "Done.", f"{dash}/calendar?post={post['id']}", asset_key))
    db.run(conn, "update scheduled_posts set status=%s, last_error=%s, locked_until=null where id=%s",
           (status, reason[:500], post["id"]))
    notify.send(conn, "manual_task", f"Manual post needed ({ctx['account_label']})", reason,
                link=f"{dash}/calendar", dedupe_key=f"manual:{post['id']}")


def final_media(conn, storage, ctx: dict) -> tuple[Path | None, Path | None]:
    """Render the final-quality file from the stored recipe, plus the selected thumbnail."""
    if ctx["kind"] in ("text_post",):
        return None, None
    recipe = (ctx["recipe"] or {}).get("render")
    if not recipe:
        raise PermanentError("No render recipe stored for this project")
    work = config.runtime().work_dir / "final" / str(ctx["project_id"])
    photos = {}
    for i, sc in enumerate(recipe["scenes"]):
        if sc.get("photo_key"):
            local = work / "photos" / Path(sc["photo_key"]).name
            if not local.exists():
                storage.download(sc["photo_key"], local)
            photos[i] = local
    out = work / f"{ctx['project_id']}_final.mp4"
    if not out.exists():
        res = rendering.render(recipe, out, "final", work_dir=config.runtime().work_dir / "render" / "shared",
                               photos=photos)
        from .. import capacity

        capacity.record_render(conn, ctx["project_id"], "final", res.seconds_taken, res.duration, res.bytes)
    thumb = None
    if ctx["kind"] == "long_video":
        t = db.one(conn, """select t.options from thumbnails t where t.project_id=%s order by selected desc, variant_label
                            limit 1""", (ctx["project_id"],))
        if t and t["options"].get("key"):
            thumb = storage.download(t["options"]["key"], work / "thumb.jpg")
    return out, thumb


def fingerprint(ctx: dict, video: Path | None) -> str:
    """SHA-256 of what would be posted: the video file's bytes, or the normalised text for text-only posts."""
    h = hashlib.sha256()
    if video is not None:
        with open(video, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        return h.hexdigest()
    text = f"{ctx.get('kind')}|{ctx.get('title') or ''}|{ctx.get('body') or ''}"
    h.update(re.sub(r"\s+", " ", text).strip().lower().encode())
    return h.hexdigest()


def unclear_attempt(conn, post_id) -> dict | None:
    return db.one(conn, """select * from publish_attempts where scheduled_post_id=%s and cleared_at is null
                             and (outcome is null or outcome = 'ambiguous') order by id desc limit 1""", (post_id,))


def _finish_attempt(conn, attempt_id, outcome: str, detail: str | None = None) -> None:
    db.run(conn, "update publish_attempts set outcome=%s, detail=%s, finished_at=now() where id=%s and outcome is null",
           (outcome, (detail or "")[:500] or None, attempt_id))


def publish_post(conn, storage, post: dict, adapters: dict | None = None, now: datetime | None = None) -> str:
    now = now or datetime.now(timezone.utc)
    adapters = adapters or {k: v() for k, v in ADAPTERS.items()}
    ctx = _context(conn, post)
    if db.one(conn, "select 1 from published_posts where scheduled_post_id=%s", (post["id"],)):
        db.run(conn, "update scheduled_posts set status='published', locked_until=null where id=%s", (post["id"],))
        return "already_published"
    if ctx and (launch := db.one(conn, """select launch_date from channel_profiles where slug=%s and launch_date is not null
                                         and launch_date > (%s at time zone %s)::date""",
                                 (ctx["channel_slug"], now, db.get_setting(conn, "timezone", "Africa/Nairobi")))):
        db.run(conn, "update scheduled_posts set status='scheduled', attempts=greatest(attempts-1,0), locked_until=null "
                     "where id=%s", (post["id"],))
        return "not_launched"  # this channel launches on launch['launch_date']: nothing goes out before
    problems = safety_problems(conn, post, ctx, now)
    if problems:
        if problems == ["paused"]:
            db.run(conn, "update scheduled_posts set status='scheduled', attempts=greatest(attempts-1,0), locked_until=null "
                         "where id=%s", (post["id"],))
            return "paused"
        db.run(conn, "update scheduled_posts set status='blocked', last_error=%s, locked_until=null where id=%s",
               ("; ".join(problems), post["id"]))
        db.audit(conn, "publish_blocked", "scheduled_post", post["id"], {"problems": problems})
        notify.send(conn, "publish_blocked", f"Post blocked ({ctx['account_label'] if ctx else '?'})",
                    "; ".join(problems), link=f"{config.runtime().dashboard_url}/calendar",
                    dedupe_key=f"blocked:{post['id']}")
        return "blocked"
    unclear = unclear_attempt(conn, post["id"])
    if unclear:  # it may already be on the platform: never send again until the owner checks
        reason = (f"An earlier attempt ({unclear['started_at']:%d %b %H:%M} UTC) didn't finish clearly. Check the "
                  "platform: if it's there, record it as posted; if not, press Try again.")
        db.run(conn, "update scheduled_posts set status='needs_review', last_error=%s, locked_until=null where id=%s",
               (reason, post["id"]))
        db.audit(conn, "publish_held_unclear_attempt", "scheduled_post", post["id"], {"attempt": unclear["id"]})
        return "needs_review"
    adapter = adapters[ctx["platform"]]
    acc = {"id": ctx["social_account_id"], "platform": ctx["platform"], "label": ctx["account_label"]}
    cap = adapter.capability(conn, acc, ctx["kind"])
    if not cap.can_publish:
        _manual(conn, post, ctx, cap.reason, storage=storage)
        return "manual"
    attempt = None
    try:
        token, tokens = oauth.access_token(conn, acc)
        video, thumb = final_media(conn, storage, ctx)
        digest = fingerprint(ctx, video)
        twin = db.one(conn, """select pp.url, pp.published_at from published_posts pp
                               where pp.social_account_id=%s and pp.content_sha256=%s limit 1""", (acc["id"], digest))
        if twin:
            detail = (f"Duplicate: this exact {'video' if video else 'text'} was already posted to {ctx['account_label']} "
                      f"on {twin['published_at']:%d %b %Y} ({twin['url'] or 'no link'}). Not sent again.")
            db.run(conn, """insert into publish_attempts (scheduled_post_id, social_account_id, content_sha256, outcome,
                                                          detail, finished_at) values (%s,%s,%s,'blocked_duplicate',%s,now())""",
                   (post["id"], acc["id"], digest, detail))
            db.run(conn, "update scheduled_posts set status='blocked', last_error=%s, locked_until=null where id=%s",
                   (detail, post["id"]))
            db.audit(conn, "publish_duplicate_blocked", "scheduled_post", post["id"], {"sha256": digest, "twin": twin["url"]})
            notify.send(conn, "publish_blocked", f"Duplicate stopped ({ctx['account_label']})", detail,
                        link=f"{config.runtime().dashboard_url}/calendar", dedupe_key=f"dup:{post['id']}")
            return "duplicate"
        try:  # written down before anything is sent; the unique index stops a second runner starting the same post
            attempt = db.one(conn, """insert into publish_attempts (scheduled_post_id, social_account_id, content_sha256)
                                      values (%s,%s,%s) returning id""", (post["id"], acc["id"], digest))["id"]
        except psycopg.errors.UniqueViolation:
            return "busy"
        db.audit(conn, "publish_attempt_started", "scheduled_post", post["id"],
                 {"attempt": attempt, "account": ctx["account_label"], "sha256": digest})
        variant = dict(ctx)
        variant["synthetic_media"] = bool((config.services()["publishing"].get("ai_disclosure") or {})
                                          .get("label_synthetic_media", False))
        if ctx["platform"] == "facebook":
            result = adapter.publish(conn, acc, variant, video, thumb, token, tokens.get("page_id") or ctx["external_id"])
        elif ctx["platform"] == "x":
            result = adapter.publish(conn, acc, variant, video, thumb, token, reference=f"x:{post['idempotency_key']}")
        else:
            result = adapter.publish(conn, acc, variant, video, thumb, token)
    except AmbiguousPublish as exc:
        if attempt:
            _finish_attempt(conn, attempt, "ambiguous", str(exc))
        db.run(conn, "update scheduled_posts set status='needs_review', last_error=%s, locked_until=null where id=%s",
               (str(exc), post["id"]))
        notify.send(conn, "publish_ambiguous", "Please check a post", str(exc),
                    link=f"{config.runtime().dashboard_url}/calendar", dedupe_key=f"ambiguous:{post['id']}")
        return "needs_review"
    except AuthError as exc:
        if attempt:
            _finish_attempt(conn, attempt, "not_sent", str(exc))
        oauth.mark_broken(conn, acc["id"], str(exc))
        _manual(conn, post, ctx, f"Connection problem: {exc}. Reconnect the account in Settings", status="needs_manual")
        return "auth_failed"
    except BudgetExceeded as exc:
        if attempt:
            _finish_attempt(conn, attempt, "not_sent", str(exc))
        _manual(conn, post, ctx, str(exc))
        return "budget"
    except (TransientError, QuotaError) as exc:  # adapters raise these only when nothing reached the platform
        if attempt:
            _finish_attempt(conn, attempt, "not_sent", str(exc))
        if post["attempts"] >= MAX_ATTEMPTS:
            _manual(conn, post, ctx, f"Failed {post['attempts']} times: {exc}", status="failed")
            return "failed"
        db.run(conn, """update scheduled_posts set status='scheduled', last_error=%s,
                        locked_until=now() + make_interval(mins => %s) where id=%s""",
               (str(exc), 15 * post["attempts"], post["id"]))
        return "retry"
    except (PermanentError, StudioError) as exc:
        if attempt:
            _finish_attempt(conn, attempt, "not_sent", str(exc))
        _manual(conn, post, ctx, f"Could not publish automatically: {exc}", status="failed")
        return "failed"
    with db.transaction(conn):
        db.run(conn, """insert into published_posts (scheduled_post_id, platform, platform_post_id, url, visibility, method,
                                                     verified_at, social_account_id, content_sha256)
                        values (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
               (post["id"], ctx["platform"], result.platform_post_id, result.url, result.visibility, result.method,
                now if result.method == "api" else None, acc["id"], digest))
        _finish_attempt(conn, attempt, "published", result.url)
        db.run(conn, "update scheduled_posts set status='published', last_error=null, locked_until=null where id=%s",
               (post["id"],))
        db.run(conn, "update content_variants set status='published' where id=%s", (ctx["id"],))
    if result.manual_followup:
        db.run(conn, """insert into manual_tasks (scheduled_post_id, platform, title, instructions, deep_link)
                        values (%s,%s,%s,%s,%s)""",
               (post["id"], ctx["platform"], f"Finish posting: {ctx.get('title') or ctx['project_title']}",
                result.manual_followup, result.url))
    notify.send(conn, "published", f"Posted to {ctx['account_label']}" + (" (needs one tap)" if result.manual_followup else ""),
                ctx.get("title") or ctx["project_title"], link=result.url, dedupe_key=f"published:{post['id']}")
    db.audit(conn, "published", "scheduled_post", post["id"], {"method": result.method, "url": result.url})
    return "published" if not result.manual_followup else "published_needs_followup"


def run_due(conn, storage, adapters=None, now: datetime | None = None) -> dict:
    out: dict[str, int] = {}
    # release locks from crashed runs, but never auto-retry 'publishing' rows that may have gone out
    db.run(conn, """update scheduled_posts set status='needs_review',
                    last_error='Runner stopped mid-publish; check the platform before retrying'
                    where status='publishing' and locked_until < now()""")
    for _ in range(20):  # batches of 10, at most 200 posts per run
        batch = claim_due(conn, now=now)
        if not batch:
            break
        for post in batch:
            res = publish_post(conn, storage, post, adapters, now)
            out[res] = out.get(res, 0) + 1
    return out


def next_due(conn, within_minutes: int = 20) -> int:
    row = db.one(conn, """select count(*) n from scheduled_posts where status='scheduled'
                          and scheduled_at <= now() + make_interval(mins => %s)""", (within_minutes,))
    return int(row["n"])
