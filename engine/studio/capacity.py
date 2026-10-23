"""Capacity planner: fit each batch inside verified free allowances, or shrink it (never pay)."""

from __future__ import annotations

import calendar
import math
import os
from datetime import date, datetime, timezone

from . import config, db

DEFAULT_LONG_SECONDS = 420          # 7-minute video
DEFAULT_SHORT_SECONDS = 45
# measured on a 4-core machine: ~1.1 s of render per 1 s of 1080p video; GitHub's 2-core runners are slower
DEFAULT_FINAL_RATIO = 2.0
DEFAULT_PREVIEW_RATIO = 1.2
AI_CALLS_PER_LONG = 12
LONG_PREVIEW_BYTES = 30_000_000
SHORT_PREVIEW_BYTES = 5_000_000


def record_render(conn, project_id, quality: str, render_seconds: float, video_seconds: float, nbytes: int) -> None:
    db.run(conn, """insert into provider_usage (provider, service, role, units, latency_ms, success)
                    values ('ffmpeg','render',%s,%s,%s,true)""",
           (quality, int(video_seconds), int(render_seconds * 1000)))


def record_github_minutes(conn, minutes: float, job: str) -> None:
    db.run(conn, """insert into provider_usage (provider, service, role, units, success)
                    values ('github_actions','github_minutes',%s,%s,true)""", (job, int(math.ceil(minutes))))


def render_ratio(conn, quality: str, default: float) -> float:
    row = db.one(conn, """select sum(latency_ms)/1000.0 secs, sum(units) video from provider_usage
                          where service='render' and role=%s and created_at > now() - interval '30 days'""", (quality,))
    if row and row["video"] and row["video"] > 60:
        ratio = float(row["secs"]) / float(row["video"])
        # local runs on fast machines would under-estimate GitHub runners; never go below 60% of default
        return max(ratio, default * 0.6)
    return default


def github_minutes_used(conn) -> int:
    row = db.one(conn, """select coalesce(sum(units),0) n from provider_usage where service='github_minutes'
                          and date_trunc('month', created_at) = date_trunc('month', now())""")
    return int(row["n"])


def storage_used(conn) -> int:
    row = db.one(conn, "select coalesce(sum(bytes),0) n from media_assets where deleted_at is null and storage_path is not null")
    return int(row["n"])


def ai_daily_capacity() -> int:
    total = 0
    for p in (config.providers().get("providers") or {}).values():
        if not p.get("enabled") or p.get("commercial_use") == "no":
            continue
        if not (os.environ.get(p.get("key_env") or "") or p.get("key_optional")):
            continue
        total += sum(m.get("daily_requests") or 0 for m in p.get("models", []) if m.get("kind", "chat") == "chat")
    return total


def plan_batch(conn, today: date | None = None) -> dict:
    today = today or datetime.now(timezone.utc).date()
    svc = config.services()
    targets = {}
    for a in config.accounts()["accounts"]:
        if a["platform"] == "youtube" and a.get("channel"):
            targets[a["channel"]] = int(a["weekly_targets"].get("long_video", 3))
    shorts_per_long = 2
    gh = svc["quotas"]["github_actions"]
    used = github_minutes_used(conn)
    days_in_month = calendar.monthrange(today.year, today.month)[1]
    weeks_left = max((days_in_month - today.day + 1) / 7, 1)
    remaining = max(gh["monthly_minutes"] - gh["reserve_minutes"] - used, 0)
    weekly_budget = remaining / weeks_left
    prev_r = render_ratio(conn, "preview", DEFAULT_PREVIEW_RATIO)
    final_r = render_ratio(conn, "final", DEFAULT_FINAL_RATIO)

    def minutes_for(n_long: int) -> float:
        n_short = n_long * shorts_per_long
        produce = n_long * (3 + DEFAULT_LONG_SECONDS * prev_r / 60) + n_short * (0.5 + DEFAULT_SHORT_SECONDS * prev_r / 60)
        publish = n_long * (1.5 + DEFAULT_LONG_SECONDS * final_r / 60) + n_short * (1 + DEFAULT_SHORT_SECONDS * final_r / 60)
        return 6 + produce + publish  # +research and housekeeping

    plan = dict(targets)
    warnings = []
    while sum(plan.values()) > 0 and minutes_for(sum(plan.values())) > weekly_budget:
        ch = max(plan, key=plan.get)
        if plan[ch] <= 1 and all(v <= 1 for v in plan.values()):
            break
        plan[ch] -= 1
    if plan != targets:
        warnings.append(f"GitHub minutes: about {weekly_budget:.0f} min/week left this month, so the plan was reduced "
                        f"from {targets} to {plan}. Tip: connect your own computer as a runner for more.")
    if minutes_for(sum(plan.values())) > weekly_budget:
        warnings.append("Even the minimum plan may exceed this month's free GitHub minutes. Jobs will pause safely when "
                        "minutes run out.")
    st = svc["quotas"]["supabase"]
    storage_free = st["storage_bytes"] * (1 - st["storage_reserve_fraction"]) - storage_used(conn)
    need = sum(plan.values()) * (LONG_PREVIEW_BYTES + shorts_per_long * SHORT_PREVIEW_BYTES)
    if need > storage_free:
        warnings.append(f"Storage: previews need ~{need / 1e6:.0f} MB but only ~{max(storage_free, 0) / 1e6:.0f} MB "
                        "is free. Old previews will be cleaned first.")
    ai_need = sum(plan.values()) * AI_CALLS_PER_LONG
    ai_cap = ai_daily_capacity()
    if ai_cap == 0:
        warnings.append("No AI provider keys are configured. Add at least GEMINI_API_KEY and GROQ_API_KEY.")
    elif ai_need > ai_cap:
        warnings.append(f"AI: batch needs ~{ai_need} requests, free capacity ~{ai_cap}/day. Work will spread over two days.")
    return {"long_per_channel": plan, "targets": targets, "github_minutes_used": used,
            "github_minutes_weekly_budget": round(weekly_budget), "estimated_minutes": round(minutes_for(sum(plan.values()))),
            "storage_free_bytes": int(storage_free), "ai_requests_needed": ai_need, "ai_daily_capacity": ai_cap,
            "warnings": warnings}
