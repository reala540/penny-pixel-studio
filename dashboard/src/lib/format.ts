import type { Channel, Platform } from "./types";

export const HOST: Record<Channel, { name: string; channel: string }> = {
  ai: { name: "Pixel", channel: "Penny & Pixel AI" },
  money: { name: "Penny", channel: "Penny & Pixel Money" },
};

export const PLATFORM_NAME: Record<Platform, string> = {
  youtube: "YouTube",
  facebook: "Facebook",
  tiktok: "TikTok",
  x: "X",
};

export const KIND_NAME: Record<string, string> = {
  long_video: "Video",
  short_video: "Short",
  reel: "Reel",
  story: "Story",
  text_post: "Post",
  image_post: "Image post",
};

const STATUS_TEXT: Record<string, string> = {
  ready_for_review: "Ready for review",
  needs_attention: "Needs a look",
  pending_approval: "Waiting for approval",
  scheduled: "Scheduled",
  publishing: "Posting now",
  published: "Published",
  needs_manual: "Post it yourself",
  needs_review: "Check on the platform",
  blocked: "On hold: facts need a re-check",
  failed: "Didn't work",
  cancelled: "Cancelled",
  approved: "Approved",
  rejected: "Discarded",
  skipped: "Skipped",
  rendering: "Making the video",
  scripting: "Writing",
  verifying: "Checking facts",
  archived: "Archived",
  draft: "Draft",
  shortlisted: "Shortlisted",
  selected: "Being made",
  produced: "Made",
  proposed: "Suggested",
  saved: "Saved",
};

export function statusText(s: string): string {
  return STATUS_TEXT[s] ?? s.replace(/_/g, " ");
}

export type Tone = "good" | "warn" | "bad" | "neutral" | "info";

export function statusTone(s: string): Tone {
  if (["published", "approved", "scheduled", "produced"].includes(s)) return "good";
  if (["needs_attention", "needs_manual", "needs_review", "pending_approval"].includes(s)) return "warn";
  if (["failed", "blocked", "rejected"].includes(s)) return "bad";
  if (["ready_for_review", "publishing", "rendering", "scripting", "selected", "shortlisted"].includes(s)) return "info";
  return "neutral";
}

export function fmtDateTime(iso: string, tz: string): string {
  return new Date(iso).toLocaleString("en-GB", { timeZone: tz, weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
}

export function fmtTime(iso: string, tz: string): string {
  return new Date(iso).toLocaleTimeString("en-GB", { timeZone: tz, hour: "2-digit", minute: "2-digit" });
}

export function fmtDuration(seconds?: number | null): string {
  if (!seconds) return "";
  const m = Math.floor(seconds / 60);
  const s = Math.round(seconds % 60);
  return m ? `${m}:${String(s).padStart(2, "0")}` : `${s}s`;
}

/** YYYY-MM-DD of a moment in the owner's timezone. */
export function localDay(iso: string | Date, tz: string): string {
  const d = typeof iso === "string" ? new Date(iso) : iso;
  return new Intl.DateTimeFormat("en-CA", { timeZone: tz, year: "numeric", month: "2-digit", day: "2-digit" }).format(d);
}

/** Seven local days starting from the Monday of the week containing `from`. */
export function weekDays(from: Date, tz: string): string[] {
  const today = localDay(from, tz);
  const base = new Date(`${today}T12:00:00Z`);
  const dow = (base.getUTCDay() + 6) % 7; // Monday = 0
  base.setUTCDate(base.getUTCDate() - dow);
  return Array.from({ length: 7 }, (_, i) => {
    const d = new Date(base);
    d.setUTCDate(base.getUTCDate() + i);
    return d.toISOString().slice(0, 10);
  });
}

export function dayLabel(day: string): { weekday: string; date: string } {
  const d = new Date(`${day}T12:00:00Z`);
  return {
    weekday: d.toLocaleDateString("en-GB", { weekday: "short", timeZone: "UTC" }),
    date: d.toLocaleDateString("en-GB", { day: "numeric", month: "short", timeZone: "UTC" }),
  };
}

/** Move a UTC instant to another local day, keeping its local time-of-day. */
export function moveToDay(iso: string, day: string, tz: string): string {
  const original = new Date(iso);
  const fromDay = localDay(original, tz);
  const shiftDays = Math.round((Date.parse(`${day}T12:00:00Z`) - Date.parse(`${fromDay}T12:00:00Z`)) / 86_400_000);
  return new Date(original.getTime() + shiftDays * 86_400_000).toISOString();
}

/** Links from outside feeds are untrusted: only allow http(s) URLs as hrefs. */
export function safeUrl(url: string | null | undefined): string | undefined {
  return url && /^https?:\/\//i.test(url) ? url : undefined;
}

export function wordCount(text: string): number {
  return text.trim() ? text.trim().split(/\s+/).length : 0;
}

export function estSeconds(text: string): number {
  return wordCount(text) / 2.5;
}
