// The header clocks: one shared instant shown in the studio's saved timezone and in Kenyan time.
// Only Intl is used. The studio zone always comes from the account's saved settings, never from this device.
import { useEffect, useState } from "react";

export const KENYA_TZ = "Africa/Nairobi";

export interface ClockFace {
  time: string;   // 17:30:05
  date: string;   // Mon 2 Nov
  zone: string;   // EST, GMT+3
  iso: string;    // for <time dateTime>
}

const cache = new Map<string, { time: Intl.DateTimeFormat; date: Intl.DateTimeFormat; zone: Intl.DateTimeFormat }>();

function formatters(tz: string) {
  let f = cache.get(tz);
  if (!f) {
    // RangeError for a name Intl doesn't know: the caller shows "unavailable" instead of guessing
    f = {
      time: new Intl.DateTimeFormat("en-GB", { timeZone: tz, hour: "2-digit", minute: "2-digit", second: "2-digit", hourCycle: "h23" }),
      date: new Intl.DateTimeFormat("en-GB", { timeZone: tz, weekday: "short", day: "numeric", month: "short" }),
      zone: new Intl.DateTimeFormat("en-US", { timeZone: tz, timeZoneName: "short" }),
    };
    cache.set(tz, f);
  }
  return f;
}

export function isValidZone(tz: unknown): tz is string {
  if (typeof tz !== "string" || !tz) return false;
  try { formatters(tz); return true; } catch { return false; }
}

/** What a clock shows for `instant` in `tz`. Throws RangeError for an unknown zone. */
export function clockFace(instant: Date, tz: string): ClockFace {
  const f = formatters(tz);
  return {
    time: f.time.format(instant),
    date: f.date.format(instant).replace(",", ""),
    zone: f.zone.formatToParts(instant).find((p) => p.type === "timeZoneName")?.value ?? tz,
    iso: instant.toISOString(),
  };
}

/** "America/New_York" → "New York". */
export function placeName(tz: string): string {
  return (tz.split("/").pop() ?? tz).replace(/_/g, " ");
}

/** The current instant, updated on every second boundary and straight away after sleep or returning to the tab. */
export function useNow(): Date {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    let timer: number | undefined;
    const tick = () => {
      setNow(new Date());
      timer = window.setTimeout(tick, 1000 - (Date.now() % 1000) + 5);  // wake just after the next second starts
    };
    const resync = () => { window.clearTimeout(timer); tick(); };
    const onVisible = () => { if (document.visibilityState === "visible") resync(); };
    tick();
    document.addEventListener("visibilitychange", onVisible);
    window.addEventListener("focus", resync);
    window.addEventListener("pageshow", resync);
    return () => {
      window.clearTimeout(timer);
      document.removeEventListener("visibilitychange", onVisible);
      window.removeEventListener("focus", resync);
      window.removeEventListener("pageshow", resync);
    };
  }, []);
  return now;
}
