"""Posting-slot planning in the owner's timezone; everything stored in UTC."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def slots(days: list[str], times: list[str], week_monday: date, tz: str, not_before: datetime | None = None) -> list[datetime]:
    """UTC datetimes for each day/time in the week starting `week_monday` (local timezone)."""
    zone = ZoneInfo(tz)
    out = []
    for day in days:
        d = week_monday + timedelta(days=DAYS.index(day.lower()[:3]))
        for t in times:
            hh, mm = (int(x) for x in t.split(":"))
            local = datetime.combine(d, time(hh, mm), tzinfo=zone)
            utc = local.astimezone(timezone.utc)
            if not_before is None or utc > not_before:
                out.append(utc)
    return sorted(out)


def next_monday(today: date) -> date:
    return today + timedelta(days=(7 - today.weekday()) % 7 or 7)


def to_local(dt: datetime, tz: str) -> datetime:
    return dt.astimezone(ZoneInfo(tz))


def balance_by_mix(items: list[dict], mix: dict[str, float], n: int) -> list[dict]:
    """Pick n items (sorted best-first per topic) so topic shares follow `mix` (e.g. 50/50)."""
    by_topic: dict[str, list[dict]] = {}
    for it in items:
        by_topic.setdefault(it["topic"], []).append(it)
    picked: list[dict] = []
    counts = {t: 0 for t in mix}
    while len(picked) < n and any(by_topic.values()):
        # topic that is furthest below its target share
        want = sorted(mix, key=lambda t: (counts[t] / max(mix[t], 1e-9)) if mix[t] > 0 else 1e9)
        for t in want + [t for t in by_topic if t not in mix]:
            if by_topic.get(t):
                picked.append(by_topic[t].pop(0))
                counts[t] = counts.get(t, 0) + 1
                break
        else:
            break
    return picked
