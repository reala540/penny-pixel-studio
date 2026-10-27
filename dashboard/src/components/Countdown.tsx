import { useNow } from "../lib/clock";

/** "in 8 h 26 min" until a post's time. Display only: it never changes when anything is posted. */
export function timeLeft(at: Date, now: Date): string {
  const ms = at.getTime() - now.getTime();
  if (ms <= 0) return "posting now";
  const mins = Math.floor(ms / 60_000);
  if (mins < 1) return "in under a minute";
  const d = Math.floor(mins / 1440), h = Math.floor((mins % 1440) / 60), m = mins % 60;
  if (d > 0) return `in ${d} day${d === 1 ? "" : "s"}${h ? ` ${h} h` : ""}`;
  if (h > 0) return `in ${h} h${m ? ` ${m} min` : ""}`;
  return `in ${m} min`;
}

/** Shown only while a post still waits; after its time the status badge says what happened. */
export default function Countdown({ at, status, className = "" }: { at: string; status: string; className?: string }) {
  const now = useNow();
  if (!["scheduled", "pending_approval"].includes(status)) return null;
  const when = new Date(at);
  return <span className={`tabular ${className}`} title={when.toISOString()}>{timeLeft(when, now)}</span>;
}
