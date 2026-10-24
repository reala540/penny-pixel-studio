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
import re
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
    """Refresh each provider's model list, then send one tiny request per provider and report which keys work."""
    from .ai import catalog
    from .ai.router import Candidate, Router
    from .ai.usage import MemoryUsageStore

    cfg = config.providers()
    found = catalog.refresh(cfg)
    if config.runtime().db_url:
        with _conn() as conn:
            db.set_setting(conn, "model_catalog", {"checked_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                                                   "providers": found})
    router = Router(MemoryUsageStore())
    results = []
    for name, p in (cfg.get("providers") or {}).items():
        key = os.environ.get(p.get("key_env") or "")
        if not key and not p.get("key_optional"):
            results.append({"provider": name, "status": "no key", "env": p.get("key_env")})
            continue
        swaps = {k: v for k, v in (found.get(name) or {}).get("missing", {}).items()}
        errors: list[str] = []
        raw: list[str] = []
        for m in (x for x in p["models"] if x.get("kind", "chat") == "chat"):
            model = catalog.effective_model(found, name, m["id"])
            if model is None:
                errors.append(f"{m['id']}: no longer offered")
                continue
            cand = Candidate(name, model, p["base_url"].rstrip("/"), key or None, 0, None, None)
            try:
                # Thinking models spend tokens reasoning before they answer, so leave room.
                res = router.complete("test", "Reply with the single word: ready", only=cand, max_tokens=600, temperature=0)
            except Exception as exc:
                errors.append(f"{model}: {_short_error(exc)}")
                raw.append(f"{model}: {str(exc)[-400:]}")
                continue
            note = f"using {model}" + (f" (replaces {m['id']})" if model != m["id"] else "")
            results.append({"provider": name, "model": model, "status": "ok", "note": note, "reply": res.text[:40]})
            break
        else:
            results.append({"provider": name, "status": "failed", "error": "; ".join(errors)[:300] or "no chat model",
                            "swaps": swaps, "details": raw})
    _print(results)
    _report_providers(results)


def _short_error(exc: Exception) -> str:
    text = str(exc)
    low = text.lower()
    if "requires payment" in low or "402" in low:
        return "this model isn't free on your plan"
    if "rate limit" in low or "quota" in low or "429" in low:
        return "free limit reached or the free plan isn't switched on in the provider's console"
    if "key rejected" in low or "401" in low or "403" in low:
        return "the API key was rejected: copy it again"
    if "404" in low or "410" in low or "not found" in low or "unavailable" in low:
        return "model not available"
    if "empty reply" in low:
        return "no answer (model busy or still thinking)"
    return text[:120]


def _report_providers(results: list[dict]) -> None:
    """Save the key check where the dashboard (and the run summary) can show it."""
    icon = {"ok": "✅", "no key": "⚪", "failed": "❌"}
    lines = ["### AI keys", "", "| Provider | Result | Note |", "|---|---|---|"]
    for r in results:
        note = r.get("error") or r.get("note") or (f"set {r['env']} to use it" if r.get("env") else r.get("model", ""))
        lines.append(f"| {r['provider']} | {icon.get(r['status'], '')} {r['status']} | {str(note).replace('|', '/')} |")
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
    if config.runtime().db_url:
        with _conn() as conn:
            db.set_setting(conn, "provider_check", {"checked_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                                                   "results": results})


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


def explain_error(e: BaseException) -> str:
    """A plain-language reason for a failed run, with any password hidden."""
    text = str(e.code if isinstance(e, SystemExit) else e) or type(e).__name__
    text = re.sub(r"(postgres(?:ql)?://[^:/@\s]+:)[^@\s]+@", r"\1***@", text)
    low = text.lower()
    hints = [
        ("password authentication failed", "The database password in SUPABASE_DB_URL is wrong. Reset it in Supabase "
         "(Project Settings > Database) and update the secret."),
        ("tenant or user not found", "SUPABASE_DB_URL has the wrong user or region. Copy it again from Supabase: "
         "Connect > Connection string > Session pooler."),
        ("network is unreachable", "GitHub can't reach the direct database address. Use the Session pooler address "
         "from Supabase (Connect > Connection string > Session pooler)."),
        ("could not translate host name", "The host in SUPABASE_DB_URL is wrong or unreachable. Use the Session pooler "
         "address from Supabase (Connect > Connection string > Session pooler)."),
        ("invalid dsn", "SUPABASE_DB_URL isn't a valid address. If the password has symbols like @ # / ? %, reset it "
         "to letters and numbers only."),
        ("missing \"=\"", "SUPABASE_DB_URL isn't a valid address. It must start with postgresql:// and contain no spaces "
         "or [brackets]."),
    ]
    for needle, hint in hints:
        if needle in low:
            return f"{hint} (Details: {text[:300]})"
    return text[:500]


def _annotate(e: BaseException) -> None:
    if os.environ.get("GITHUB_ACTIONS") != "true":
        return
    msg = explain_error(e).replace("%", "%25").replace("\r", "").replace("\n", " ")
    print(f"::error title=studio failed::{msg}", flush=True)


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
    except (SystemExit, Exception) as e:
        if not (isinstance(e, SystemExit) and e.code in (None, 0)):
            _annotate(e)
        raise
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
