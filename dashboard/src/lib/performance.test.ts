import { describe, expect, it } from "vitest";
import { emptyReason, fmtMinutes, fmtSeconds, groupBy, weekdayHour, type PostRow } from "./performance";

const row = (over: Partial<PostRow>): PostRow => ({ published_post_id: "p", platform: "youtube", account_label: "YouTube AI", kind: "long_video",
  channel_slug: "ai", project_id: "x", title: "T", url: null, published_at: "2026-10-27T22:00:00Z", collected_on: "2026-10-29",
  views: null, watch_minutes: null, avg_view_seconds: null, impressions: null, ctr: null, likes: null, comments: null, shares: null,
  subscribers_gained: null, revenue_usd: null, missing: [], ...over });

describe("performance numbers", () => {
  it("say why a number is missing instead of showing zero", () => {
    expect(emptyReason(row({ platform: "x" }), "views")).toMatch(/charges/);
    expect(emptyReason(row({ platform: "facebook" }), "views")).toMatch(/insights permission/);
    expect(emptyReason(row({ collected_on: null }), "views")).toMatch(/Not collected yet/);
    expect(emptyReason(row({ missing: ["ctr"] }), "ctr")).toMatch(/Not available from YouTube/);
  });
  it("averages only posts that have numbers", () => {
    const g = groupBy([row({ channel_slug: "ai", views: 100 }), row({ channel_slug: "ai", views: null }), row({ channel_slug: "money", views: 300 })],
      (r) => r.channel_slug);
    expect(g).toEqual([{ key: "money", posts: 1, withData: 1, views: 300, avgViews: 300 }, { key: "ai", posts: 2, withData: 1, views: 100, avgViews: 100 }]);
  });
  it("formats time and finds the posting day in the studio's timezone", () => {
    expect(fmtMinutes(45)).toBe("45 min");
    expect(fmtMinutes(90)).toBe("1.5 h");
    expect(fmtSeconds(125)).toBe("2:05");
    expect(weekdayHour("2026-10-27T22:00:00Z", "America/New_York")).toEqual({ day: "Tuesday", hour: "18:00" });
  });
});
