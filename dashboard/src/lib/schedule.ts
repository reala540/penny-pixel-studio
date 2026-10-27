// Posting schedule editor helpers (pure, so they're unit-tested).
import type { Platform } from "./types";

export const DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"] as const;
export type Day = (typeof DAYS)[number];
export const DAY_LABEL: Record<Day, string> = { mon: "Mon", tue: "Tue", wed: "Wed", thu: "Thu", fri: "Fri", sat: "Sat", sun: "Sun" };

export interface ScheduleDraft {
  enabled: boolean;
  posting_days: Day[];
  posting_times: string[];
  shorts_days: Day[];
  shorts_times: string[];
  targets: Record<string, number>;
}

/** Post types and which slot group they use. Facebook Reels, text posts and long videos share the same slots, in that
 *  order; a Story takes no slot of its own: it goes up STORY_DELAY_HOURS after its Reel. */
export const KINDS: Record<Platform, { kind: string; label: string; group: "posting" | "shorts" | "after_reel" }[]> = {
  youtube: [{ kind: "long_video", label: "Long videos", group: "posting" }, { kind: "short_video", label: "Shorts", group: "shorts" }],
  facebook: [{ kind: "reel", label: "Reels", group: "posting" }, { kind: "text_post", label: "Text posts", group: "posting" },
    { kind: "long_video", label: "Long videos", group: "posting" }, { kind: "story", label: "Stories", group: "after_reel" }],
  tiktok: [{ kind: "short_video", label: "Videos", group: "posting" }],
  x: [{ kind: "text_post", label: "Posts", group: "posting" }],
};

export const STORY_DELAY_HOURS = 3;
const laterBy = (time: string, hours: number) => {
  const m = (minutes(time) + hours * 60) % (24 * 60);
  return { time: `${String(Math.floor(m / 60)).padStart(2, "0")}:${String(m % 60).padStart(2, "0")}`, nextDay: minutes(time) + hours * 60 >= 24 * 60 };
};

/** Roughly what YouTube's free API quota allows per day (10,000 units, about 1,600 per upload). */
export const YOUTUBE_UPLOADS_PER_DAY = 6;

const asDays = (v: unknown): Day[] => (Array.isArray(v) ? v.map((d) => String(d).toLowerCase().slice(0, 3)).filter((d): d is Day => (DAYS as readonly string[]).includes(d)) : []);
const asTimes = (v: unknown): string[] => (Array.isArray(v) ? v.map(String).filter((t) => /^([01]\d|2[0-3]):[0-5]\d$/.test(t)) : []);

export function draftFrom(platform: Platform, enabled: boolean, wt: Record<string, unknown>): ScheduleDraft {
  const targets: Record<string, number> = {};
  for (const k of KINDS[platform]) targets[k.kind] = Number(wt[k.kind] ?? 0) || 0;
  return {
    enabled, targets,
    posting_days: asDays(wt.posting_days), posting_times: asTimes(wt.posting_times).sort(),
    shorts_days: asDays(wt.shorts_days), shorts_times: asTimes(wt.shorts_times).sort(),
  };
}

/** What to save. A post type that was never saved and is still 0 is left out, so a schedule still saves on a database
 *  that doesn't know that type yet (for example Facebook Stories before migration 16). */
export function payload(platform: Platform, d: ScheduleDraft, saved: Record<string, unknown> = {}): Record<string, unknown> {
  const targets = Object.fromEntries(Object.entries(d.targets).filter(([k, n]) => n > 0 || k in saved));
  const out: Record<string, unknown> = { enabled: d.enabled, posting_days: d.posting_days, posting_times: d.posting_times, targets };
  if (platform === "youtube") Object.assign(out, { shorts_days: d.shorts_days, shorts_times: d.shorts_times });
  return out;
}

const minutes = (t: string) => Number(t.slice(0, 2)) * 60 + Number(t.slice(3));

export function slotsPerWeek(d: ScheduleDraft, group: "posting" | "shorts"): number {
  return group === "posting" ? d.posting_days.length * d.posting_times.length : d.shorts_days.length * d.shorts_times.length;
}

/** What goes out on each day: [{time, label}], in time order. Only as many slots as the weekly targets fill. */
export function weekPreview(platform: Platform, d: ScheduleDraft): Record<Day, { time: string; label: string }[]> {
  const out = Object.fromEntries(DAYS.map((day) => [day, [] as { time: string; label: string }[]])) as Record<Day, { time: string; label: string }[]>;
  if (!d.enabled) return out;
  for (const group of ["posting", "shorts"] as const) {
    const kinds = KINDS[platform].filter((k) => k.group === group);
    if (!kinds.length) continue;
    const days = group === "posting" ? d.posting_days : d.shorts_days;
    const times = group === "posting" ? d.posting_times : d.shorts_times;
    const slots = DAYS.filter((day) => days.includes(day)).flatMap((day) => [...times].sort().map((time) => ({ day, time })));
    let i = 0;
    for (const k of kinds) {
      for (let n = 0; n < (d.targets[k.kind] ?? 0) && i < slots.length; n++, i++) {
        out[slots[i].day].push({ time: slots[i].time, label: k.label });
        if (k.kind === "reel" && n < (d.targets.story ?? 0)) {  // its Story, a few hours later
          const later = laterBy(slots[i].time, STORY_DELAY_HOURS);
          const day = later.nextDay ? DAYS[(DAYS.indexOf(slots[i].day) + 1) % 7] : slots[i].day;
          out[day].push({ time: later.time, label: "Story" });
        }
      }
    }
  }
  for (const day of DAYS) out[day].sort((a, b) => a.time.localeCompare(b.time));
  return out;
}

export function totalPerWeek(platform: Platform, d: ScheduleDraft): number {
  return Object.values(weekPreview(platform, d)).reduce((a, x) => a + x.length, 0);
}

export function warnings(platform: Platform, d: ScheduleDraft): string[] {
  const w: string[] = [];
  if (!d.enabled) return ["Paused: nothing is planned for this account until you switch it back on."];
  for (const group of ["posting", "shorts"] as const) {
    const kinds = KINDS[platform].filter((k) => k.group === group);
    if (!kinds.length) continue;
    const want = kinds.reduce((a, k) => a + (d.targets[k.kind] ?? 0), 0);
    const have = slotsPerWeek(d, group);
    const what = kinds.map((k) => k.label.toLowerCase()).join(" and ");
    if (want > 0 && have === 0) w.push(`No ${group === "shorts" ? "Shorts " : ""}days or times are chosen, so no ${what} will be posted.`);
    else if (want > have) w.push(`You asked for ${want} ${what} a week but chose only ${have} slot${have === 1 ? "" : "s"}. Only ${have} will be posted; add days or times.`);
    const times = [...(group === "posting" ? d.posting_times : d.shorts_times)].sort();
    for (let i = 1; i < times.length; i++) {
      if (minutes(times[i]) - minutes(times[i - 1]) < 60) w.push(`${times[i - 1]} and ${times[i]} are less than an hour apart. Posts that close together usually reach fewer people.`);
    }
  }
  if (platform === "facebook" && (d.targets.story ?? 0) > (d.targets.reel ?? 0))
    w.push(`Each Story is one of your Reels shown again ${STORY_DELAY_HOURS} hours later, so only ${d.targets.reel ?? 0} Stor${(d.targets.reel ?? 0) === 1 ? "y" : "ies"} will be posted.`);
  if (platform === "youtube") {
    const busiest = Math.max(...Object.values(weekPreview(platform, d)).map((x) => x.length));
    if (busiest > YOUTUBE_UPLOADS_PER_DAY) w.push(`One day has ${busiest} uploads. YouTube's free API allows about ${YOUTUBE_UPLOADS_PER_DAY} a day per channel project; the rest would wait.`);
    for (const day of DAYS) {
      if (!d.posting_days.includes(day) || !d.shorts_days.includes(day)) continue;
      for (const a of d.posting_times) for (const b of d.shorts_times) {
        if (Math.abs(minutes(a) - minutes(b)) < 60) { w.push(`On ${DAY_LABEL[day]} a long video (${a}) and a Short (${b}) are less than an hour apart.`); break; }
      }
    }
  }
  return [...new Set(w)];
}
