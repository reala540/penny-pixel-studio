// Performance numbers as the platforms gave them. A number that wasn't given is "not available", never zero.
export interface PostRow {
  published_post_id: string; platform: string; account_label: string; kind: string; channel_slug: "ai" | "money";
  project_id: string; title: string; url: string | null; published_at: string; collected_on: string | null;
  views: number | null; watch_minutes: number | null; avg_view_seconds: number | null; impressions: number | null; ctr: number | null;
  likes: number | null; comments: number | null; shares: number | null; subscribers_gained: number | null; revenue_usd: number | null;
  missing: string[] | null;
}

/** Why a cell is empty: the platform isn't read yet, nothing has been collected, or the platform didn't give it. */
export function emptyReason(row: Pick<PostRow, "platform" | "collected_on" | "missing">, column: string): string {
  if (row.platform === "x") return "Not read: X charges for reading post stats";
  if (row.platform === "facebook") return "Not collected yet: needs the Facebook Page insights permission";
  if (row.platform !== "youtube") return "Not collected for this platform yet";
  if (!row.collected_on) return "Not collected yet (the next daily check reads it)";
  if ((row.missing ?? []).some((m) => m === column || m.startsWith("all"))) return "Not available from YouTube for this video";
  return "Not available";
}

export const fmtCount = (n: number | null | undefined) => (n == null ? null : Math.round(Number(n)).toLocaleString("en-US"));
export const fmtMinutes = (m: number | null | undefined) => {
  if (m == null) return null;
  const v = Number(m);
  return v >= 60 ? `${(v / 60).toFixed(v >= 600 ? 0 : 1)} h` : `${Math.round(v)} min`;
};
export const fmtSeconds = (s: number | null | undefined) => (s == null ? null : `${Math.floor(Number(s) / 60)}:${String(Math.round(Number(s) % 60)).padStart(2, "0")}`);
export const fmtPercent = (p: number | null | undefined) => (p == null ? null : `${Number(p).toFixed(1)}%`);

export interface Group { key: string; posts: number; withData: number; views: number; avgViews: number | null }

/** Posts grouped by a key; averages only count posts that have numbers. */
export function groupBy(rows: PostRow[], key: (r: PostRow) => string): Group[] {
  const map = new Map<string, Group>();
  for (const r of rows) {
    const k = key(r);
    const g = map.get(k) ?? { key: k, posts: 0, withData: 0, views: 0, avgViews: null };
    g.posts += 1;
    if (r.views != null) { g.withData += 1; g.views += Number(r.views); }
    map.set(k, g);
  }
  return [...map.values()].map((g) => ({ ...g, avgViews: g.withData ? Math.round(g.views / g.withData) : null }))
    .sort((a, b) => (b.avgViews ?? -1) - (a.avgViews ?? -1));
}

export function weekdayHour(iso: string, tz: string): { day: string; hour: string } {
  const d = new Date(iso);
  return {
    day: new Intl.DateTimeFormat("en-GB", { timeZone: tz, weekday: "long" }).format(d),
    hour: new Intl.DateTimeFormat("en-GB", { timeZone: tz, hour: "2-digit", hourCycle: "h23" }).format(d) + ":00",
  };
}

export const KIND_LABEL: Record<string, string> = { long_video: "Long videos", short_video: "Shorts", reel: "Reels", story: "Stories", text_post: "Text posts" };
