"""Owner-approved spending (only X). Reserve before a chargeable call, commit or release after.

Local enforcement cannot stop charges made outside this app — the guide tells the owner to
set X's own spending limit too.
"""

from __future__ import annotations

from . import config, db
from .errors import BudgetExceeded


def sync_budgets(conn) -> None:
    for service, b in (config.services().get("budgets") or {}).items():
        cap = min(float(b["monthly_cap_usd"]), 1.00) if service == "x_api" else float(b["monthly_cap_usd"])
        db.run(conn, """insert into budgets (service, monthly_cap_usd, hard_stop, notes)
                        values (%s,%s,%s,%s)
                        on conflict (service) do nothing""",
               (service, cap, bool(b.get("hard_stop", True)), "from config/services.yaml"))


def reserve(conn, service: str, amount: float, reference: str) -> None:
    row = db.one(conn, "select public.reserve_budget(%s::text, %s::numeric, %s::text) ok", (service, amount, reference))
    if not row or not row["ok"]:
        raise BudgetExceeded(f"{service}: reserving ${amount:.3f} would exceed the monthly cap (or budget disabled)")


def commit(conn, reference: str, actual: float | None = None) -> None:
    db.run(conn, """update budget_reservations set status='committed',
                    amount_usd=coalesce(%s, amount_usd) where reference=%s""", (actual, reference))
    row = db.one(conn, "select service, amount_usd from budget_reservations where reference=%s", (reference,))
    if row:
        db.run(conn, """insert into provider_usage (provider, service, cost_usd, success)
                        values (%s, %s, %s, true)""", (row["service"], row["service"], row["amount_usd"]))


def release(conn, reference: str) -> None:
    db.run(conn, "update budget_reservations set status='released' where reference=%s and status='reserved'",
           (reference,))


def month_summary(conn, service: str) -> dict:
    row = db.one(conn, """
        select b.monthly_cap_usd cap, b.enabled,
               coalesce(sum(r.amount_usd) filter (where r.status='committed'),0) spent,
               coalesce(sum(r.amount_usd) filter (where r.status='reserved'),0) reserved
          from budgets b
          left join budget_reservations r on r.service=b.service
               and r.month = date_trunc('month', now() at time zone 'utc')::date
         where b.service=%s group by b.monthly_cap_usd, b.enabled""", (service,))
    if not row:
        return {"cap": 0, "spent": 0, "reserved": 0, "remaining": 0, "enabled": False}
    remaining = float(row["cap"]) - float(row["spent"]) - float(row["reserved"])
    return {"cap": float(row["cap"]), "spent": float(row["spent"]), "reserved": float(row["reserved"]),
            "remaining": max(remaining, 0.0), "enabled": row["enabled"]}
