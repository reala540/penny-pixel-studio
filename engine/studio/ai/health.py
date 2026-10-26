"""Paused AI models come back by themselves.

A model the provider retired, or one that isn't free on the plan, pauses itself (see Router.pause). This module
re-tests paused models on a schedule with one tiny request, switches them back on the moment they work again and
tells the owner in one grouped message. After the last scheduled re-test it stops trying and asks the owner instead:
the model stays paused (nothing is deleted) until they decide.
"""

from __future__ import annotations

from datetime import datetime, timezone

from .. import config, db, notify

DAY = 24 * 3600
# reason: (seconds until the next re-test, how many re-tests before asking the owner)
SCHEDULE = {"retired": (7 * DAY, 4), "payment": (DAY, 7)}
WHY = {"retired": "the provider retired it", "payment": "it isn't free on your plan"}


def due(conn, now: datetime | None = None) -> list[dict]:
    return db.all_(conn, """select m.provider, m.model, m.pause_reason, m.checks, m.paused_at, p.base_url
                              from ai_model_configs m join ai_providers p on p.name = m.provider
                             where m.pause_reason is not null and m.enabled and p.enabled
                               and m.next_check_at is not null and m.next_check_at <= %s
                             order by m.next_check_at""", (now or datetime.now(timezone.utc),))


def recheck(conn, now: datetime | None = None) -> dict:
    """Re-test every paused model that is due. Returns {"back": [...], "still": [...], "given_up": [...]}."""
    from .router import Candidate, Router
    from .usage import ProbeStore

    rows = due(conn, now)
    out: dict = {"back": [], "still": [], "given_up": []}
    if not rows:
        return out
    store = ProbeStore(conn)
    router = Router(store)
    providers = router.cfg.get("providers") or {}
    for r in rows:
        p = providers.get(r["provider"]) or {}
        name = f"{r['model']} ({r['provider']})"
        cand = Candidate(r["provider"], r["model"], (p.get("base_url") or r["base_url"]).rstrip("/"), router._env_key(p),
                         0, None, None)
        try:
            router.complete("test", "Reply with the single word: ready", only=cand, max_tokens=600, temperature=0)
        except Exception as exc:
            checks = r["checks"] + 1
            wait, limit = SCHEDULE[r["pause_reason"]]
            if checks >= limit:
                db.run(conn, """update ai_model_configs set checks=%s, next_check_at=null, pause_detail=%s
                                where provider=%s and model=%s""", (checks, str(exc)[:300], r["provider"], r["model"]))
                out["given_up"].append({"model": name, "reason": r["pause_reason"], "checks": checks})
            else:
                db.run(conn, """update ai_model_configs set checks=%s, next_check_at=now() + make_interval(secs => %s),
                                       pause_detail=%s where provider=%s and model=%s""",
                       (checks, wait, str(exc)[:300], r["provider"], r["model"]))
                out["still"].append({"model": name, "reason": r["pause_reason"], "checks": checks})
            continue
        db.run(conn, """update ai_model_configs set pause_reason=null, paused_at=null, next_check_at=null, checks=0,
                               pause_detail=null where provider=%s and model=%s""", (r["provider"], r["model"]))
        db.run(conn, "insert into audit_logs (actor, action, target_type, target_id, details) values "
                     "('engine','ai_model_back','ai_model',%s,%s)", (r["model"], db.j({"provider": r["provider"]})))
        out["back"].append({"model": name, "reason": r["pause_reason"]})
    link = f"{config.runtime().dashboard_url}/settings/ai"
    stamp = (now or datetime.now(timezone.utc)).strftime("%Y%m%d%H")
    if out["back"]:  # one grouped message, never one per model
        notify.send(conn, "ai_model_back", f"Back at work: {len(out['back'])} AI model{'s' if len(out['back']) > 1 else ''}",
                    "These work again and are back in the team: " + ", ".join(b["model"] for b in out["back"]),
                    link=link, dedupe_key=f"back:{stamp}")
    if out["given_up"]:
        notify.send(conn, "ai_model_given_up", "Still not working: your decision",
                    "; ".join(f"{g['model']}: {WHY[g['reason']]} ({g['checks']} re-tests)" for g in out["given_up"])
                    + ". They stay paused. Switch them off or remove them in Settings → AI keys, or replace the key.",
                    link=link, dedupe_key=f"givenup:{stamp}")
    return out
