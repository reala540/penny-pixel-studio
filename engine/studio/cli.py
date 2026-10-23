"""Command line entry point used by GitHub Actions and by the owner's computer.

    studio migrate         create/upgrade the database tables (safe to repeat)
    studio init            sync config into the database (safe to repeat)
    studio research        Saturday: collect sources + shortlist ideas
    studio produce         Sunday: scripts, previews, thumbnails, posting plan
    studio publish         publish approved posts that are due
    studio queue           run jobs the owner requested from the dashboard
    studio maintain        cleanup, token health, freshness checks
    studio demo            render the two channel trailers (no AI keys needed)
    studio benchmark       measure render speed/size and recommend a weekly plan
    studio capacity        show the free-capacity plan
    studio providers       test which AI provider keys work
    studio status          one-screen summary
"""

from __future__ import annotations

import argparse
import json
import os
import resource
import sys
import time
from datetime import date
from pathlib import Path

from . import config, db


def _conn():
    return db.connect(config.runtime().require_db())


def _router(conn=None):
    from .ai.router import Router
    from .ai.usage import DbUsageStore, MemoryUsageStore

    return Router(DbUsageStore(conn) if conn is not None else MemoryUsageStore())


def _print(obj) -> None:
    print(json.dumps(obj, indent=2, default=str))


def cmd_migrate(a):
    """Apply supabase/migrations/*.sql once each (tracked in studio_meta.migrations)."""
    mig_dir = config.REPO_ROOT / "supabase" / "migrations"
    with _conn() as conn:
        db.run(conn, "create schema if not exists studio_meta")
        db.run(conn, "create table if not exists studio_meta.migrations (name text primary key, applied_at timestamptz default now())")
        done = {r["name"] for r in db.all_(conn, "select name from studio_meta.migrations")}
        applied = []
        for f in sorted(mig_dir.glob("*.sql")):
            if f.name in done:
                continue
            with db.transaction(conn):
                conn.execute(f.read_text())
                db.run(conn, "insert into studio_meta.migrations (name) values (%s)", (f.name,))
            applied.append(f.name)
        _print({"applied": applied, "already": sorted(done)})


def cmd_init(a):
    from . import produce

    with _conn() as conn:
        _print(produce.sync_config(conn))


def cmd_research(a):
    from . import produce
    from .research.engine import week_start

    with _conn() as conn:
        produce.sync_config(conn)
        _print(produce.research_batch(conn, _router(conn), week_start(date.fromisoformat(a.week) if a.week else None)))


def cmd_produce(a):
    from . import produce
    from .research.engine import week_start
    from .storage import default_storage

    with _conn() as conn:
        _print(produce.produce_batch(conn, _router(conn), default_storage(),
                                     week_start(date.fromisoformat(a.week) if a.week else None)))


def cmd_publish(a):
    from .publish import runner
    from .storage import default_storage

    with _conn() as conn:
        _print(runner.run_due(conn, default_storage()))


def cmd_queue(a):
    from . import jobs, maintenance
    from .storage import default_storage

    with _conn() as conn:
        jobs.reset_stale_running(conn)
        _print(maintenance.process_owner_jobs(conn, _router(conn), default_storage()))


def cmd_maintain(a):
    from . import maintenance, oauth
    from .storage import default_storage

    with _conn() as conn:
        out = {"cleanup": maintenance.cleanup(conn, default_storage()), "expired": maintenance.expire_stale(conn)}
        if config.runtime().token_key:
            out["tokens"] = oauth.check_health(conn)
            for t in out["tokens"]:
                if t["ok"] is False:
                    from . import notify

                    notify.send(conn, "token", f"Reconnect {t['account']}", t["error"],
                                link=f"{config.runtime().dashboard_url}/settings",
                                dedupe_key=f"token:{t['account']}:{date.today()}")
        _print(out)


def _render_trailers(out_dir: Path, quality: str) -> list[dict]:
    from .demo import SHORT_TRAILERS, TRAILERS
    from .media import render as rendering

    results = []
    for channel in ("ai", "money"):
        for fmt, src in (("long", TRAILERS[channel]), ("short", SHORT_TRAILERS[channel])):
            recipe = rendering.recipe_from_script(src, channel, fmt, src["title"])
            res = rendering.render(recipe, out_dir / f"trailer_{channel}_{fmt}_{quality}.mp4", quality)
            results.append({"channel": channel, "format": fmt, "quality": quality, "file": str(res.video),
                            "video_seconds": round(res.duration, 1), "render_seconds": res.seconds_taken,
                            "megabytes": round(res.bytes / 1e6, 2), "cached_scenes": res.cached_scenes,
                            "recipe": recipe})
    return results


def cmd_demo(a):
    out_dir = config.runtime().work_dir / "demo"
    results = _render_trailers(out_dir, a.quality)
    if a.to_review:
        with _conn() as conn:
            _register_trailers(conn, results)
    _print([{k: v for k, v in r.items() if k != "recipe"} for r in results])


def _register_trailers(conn, results):
    """Put the trailers into the review queue so the owner can approve and publish them."""
    from . import produce
    from .research.engine import week_start
    from .storage import default_storage

    storage = default_storage()
    week = week_start()
    for r in results:
        if r["quality"] != "preview":
            continue
        from .demo import SHORT_TRAILERS, TRAILERS

        src = (TRAILERS if r["format"] == "long" else SHORT_TRAILERS)[r["channel"]]
        p = produce.ensure_project(conn, r["channel"], r["format"], src["title"], week, key=f"trailer:{r['channel']}:{r['format']}")
        if p["current_script_version_id"] is None:
            produce.save_script(conn, p["id"], src, "ai", [{"step": "trailer", "provider": "handwritten"}])
        pkg = {"youtube_title": src["title"], "youtube_description": f"{src['hook']}\n\n{src.get('cta', '')}".strip(),
               "tags": [], "thumbnail_headlines": [src["title"]], "x_post": "", "facebook_post": src["hook"]}
        key = storage.upload(f"projects/{p['id']}/preview.mp4", Path(r["file"]), "video/mp4")
        db.run(conn, """insert into media_assets (project_id, kind, storage_path, bytes, duration_seconds)
                        values (%s,'preview_video',%s,%s,%s)""", (p["id"], key, Path(r["file"]).stat().st_size, r["video_seconds"]))
        db.run(conn, """update content_projects set recipe = recipe || %s, status='ready_for_review',
                        quality_report=%s where id=%s""",
               (db.j({"render": r["recipe"], "preview_key": key, "package": pkg, "preview_seconds": r["video_seconds"]}),
                db.j({"issues": [], "note": "Channel trailer: hand-written, no factual claims"}), p["id"]))
        if r["format"] == "long":
            produce.make_thumbnails(conn, storage, p["id"], r["channel"])
    produce.plan_distribution(conn, week)


def cmd_benchmark(a):
    from . import capacity

    out_dir = config.runtime().work_dir / "benchmark"
    t0 = time.monotonic()
    results = _render_trailers(out_dir, "preview") + _render_trailers(out_dir, "final")
    peak_mb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024 + \
        resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss / 1024
    final = [r for r in results if r["quality"] == "final"]
    ratio = sum(r["render_seconds"] for r in final) / max(sum(r["video_seconds"] for r in final), 1)
    prev = [r for r in results if r["quality"] == "preview"]
    pratio = sum(r["render_seconds"] for r in prev) / max(sum(r["video_seconds"] for r in prev), 1)
    mb_per_min = sum(r["megabytes"] for r in final) / max(sum(r["video_seconds"] for r in final) / 60, 0.1)
    long_min = capacity.DEFAULT_LONG_SECONDS / 60
    weekly = {"long_videos": 6, "shorts": 12}
    est = (weekly["long_videos"] * long_min * (pratio + ratio) + weekly["shorts"] * 0.75 * (pratio + ratio))
    report = {"cpu_count": os.cpu_count(), "peak_memory_mb": round(peak_mb), "wall_seconds": round(time.monotonic() - t0, 1),
              "final_render_seconds_per_video_second": round(ratio, 2),
              "preview_render_seconds_per_video_second": round(pratio, 2),
              "final_megabytes_per_minute": round(mb_per_min, 1),
              "estimated_weekly_render_minutes_full_plan": round(est),
              "github_free_minutes_per_week": round(2000 / 4.3),
              "note": "Rendering only. AI time adds about 3 minutes per long video. GitHub's 2-core runners are "
                      "usually 1.5-2x slower than this machine if it has 4+ cores.",
              "files": [{k: v for k, v in r.items() if k != "recipe"} for r in results]}
    fits = est * (2 if (os.cpu_count() or 2) >= 4 else 1) < 2000 / 4.3 - 60
    report["recommendation"] = ("Full plan (6 long + 12 Shorts/week) fits the free GitHub minutes."
                                if fits else "Full plan may not fit free GitHub minutes: start with 2 long videos per "
                                             "channel per week, or add your own computer as a runner.")
    _print(report)
    if config.runtime().db_url:
        with _conn() as conn:
            for r in results:
                capacity.record_render(conn, None, r["quality"], r["render_seconds"], r["video_seconds"],
                                       int(r["megabytes"] * 1e6))


def cmd_capacity(a):
    from . import capacity

    with _conn() as conn:
        _print(capacity.plan_batch(conn))


def cmd_providers(a):
    """Send one tiny request to every configured model and report which keys work."""
    from .ai.router import Router
    from .ai.usage import MemoryUsageStore

    router = Router(MemoryUsageStore())
    results = []
    for name, p in (config.providers().get("providers") or {}).items():
        key = os.environ.get(p.get("key_env") or "")
        if not key and not p.get("key_optional"):
            results.append({"provider": name, "status": "no key", "env": p.get("key_env")})
            continue
        model = next((m for m in p["models"] if m.get("kind", "chat") == "chat"), None)
        if model is None:
            continue
        from .ai.router import Candidate

        cand = Candidate(name, model["id"], p["base_url"].rstrip("/"), key or None, 0, None, None)
        try:
            res = router.complete("test", "Reply with the single word: ready", only=cand, max_tokens=20, temperature=0)
            results.append({"provider": name, "model": model["id"], "status": "ok", "reply": res.text[:40]})
        except Exception as exc:
            results.append({"provider": name, "model": model["id"], "status": "failed", "error": str(exc)[:160]})
    _print(results)


def cmd_status(a):
    from . import budget, capacity

    with _conn() as conn:
        _print({
            "paused": db.get_setting(conn, "paused", False),
            "projects": db.all_(conn, "select status, count(*) from content_projects group by status order by 1"),
            "posts": db.all_(conn, "select status, count(*) from scheduled_posts group by status order by 1"),
            "jobs_failed_7d": db.one(conn, "select count(*) n from generation_jobs where status='failed' and created_at > now()-interval '7 days'")["n"],
            "x_budget": budget.month_summary(conn, "x_api"),
            "github_minutes_this_month": capacity.github_minutes_used(conn),
        })


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="studio", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("migrate").set_defaults(fn=cmd_migrate)
    sub.add_parser("init").set_defaults(fn=cmd_init)
    for name, fn in (("research", cmd_research), ("produce", cmd_produce)):
        p = sub.add_parser(name)
        p.add_argument("--week", help="Monday of the batch week, YYYY-MM-DD (default: this week)")
        p.set_defaults(fn=fn)
    sub.add_parser("publish").set_defaults(fn=cmd_publish)
    sub.add_parser("queue").set_defaults(fn=cmd_queue)
    sub.add_parser("maintain").set_defaults(fn=cmd_maintain)
    d = sub.add_parser("demo")
    d.add_argument("--quality", choices=["preview", "final"], default="preview")
    d.add_argument("--to-review", action="store_true", help="also add the trailers to the review queue")
    d.set_defaults(fn=cmd_demo)
    sub.add_parser("benchmark").set_defaults(fn=cmd_benchmark)
    sub.add_parser("capacity").set_defaults(fn=cmd_capacity)
    sub.add_parser("providers").set_defaults(fn=cmd_providers)
    sub.add_parser("status").set_defaults(fn=cmd_status)
    a = ap.parse_args(argv)
    started = time.monotonic()
    try:
        a.fn(a)
    finally:
        if os.environ.get("GITHUB_ACTIONS") == "true" and config.runtime().db_url:
            try:
                from . import capacity

                with _conn() as conn:
                    capacity.record_github_minutes(conn, (time.monotonic() - started) / 60 + 0.5, a.cmd)
            except Exception:
                pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
