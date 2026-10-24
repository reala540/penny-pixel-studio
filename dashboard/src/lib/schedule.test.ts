import { describe, expect, it } from "vitest";
import { draftFrom, payload, totalPerWeek, warnings, weekPreview } from "./schedule";

const yt = () => draftFrom("youtube", true, {
  long_video: 3, short_video: 6, posting_days: ["mon", "wed", "fri"], posting_times: ["18:00"],
  shorts_days: ["mon", "tue", "wed", "thu", "fri", "sat"], shorts_times: ["12:00"],
});

describe("posting schedule", () => {
  it("reads the stored schedule and previews the week", () => {
    const d = yt();
    const week = weekPreview("youtube", d);
    expect(week.mon).toEqual([{ time: "12:00", label: "Shorts" }, { time: "18:00", label: "Long videos" }]);
    expect(week.sun).toEqual([]);
    expect(totalPerWeek("youtube", d)).toBe(9);
    expect(warnings("youtube", d)).toEqual([]);
  });

  it("only fills as many slots as the targets ask for, and Facebook kinds share slots", () => {
    const fb = draftFrom("facebook", true, { reel: 3, text_post: 2, posting_days: ["mon", "wed", "fri", "sat", "sun"], posting_times: ["12:30"] });
    const week = weekPreview("facebook", fb);
    expect([week.mon[0].label, week.wed[0].label, week.fri[0].label, week.sat[0].label, week.sun[0].label])
      .toEqual(["Reels", "Reels", "Reels", "Text posts", "Text posts"]);
    expect(totalPerWeek("facebook", { ...fb, targets: { reel: 1, text_post: 0 } })).toBe(1);
  });

  it("warns when the targets don't fit, times are too close or YouTube would hit its limit", () => {
    const x = draftFrom("x", true, { text_post: 5, posting_days: ["mon"], posting_times: ["08:30", "09:00"] });
    const w = warnings("x", x);
    expect(w.some((m) => m.includes("only 2 slots"))).toBe(true);
    expect(w.some((m) => m.includes("less than an hour apart"))).toBe(true);
    expect(warnings("x", { ...x, posting_days: [] }).some((m) => m.includes("No days or times"))).toBe(true);
    const busy = { ...yt(), targets: { long_video: 7, short_video: 7 }, posting_days: ["mon" as const], posting_times: ["06:00", "09:00", "12:00", "15:00"],
      shorts_days: ["mon" as const], shorts_times: ["07:30", "10:30", "13:30", "16:30"] };
    expect(warnings("youtube", busy).some((m) => m.includes("free API allows about 6"))).toBe(true);
    expect(warnings("youtube", { ...yt(), shorts_times: ["17:30"] }).some((m) => m.includes("long video (18:00) and a Short (17:30)"))).toBe(true);
  });

  it("a paused account plans nothing; only YouTube sends Shorts times", () => {
    const d = { ...yt(), enabled: false };
    expect(totalPerWeek("youtube", d)).toBe(0);
    expect(warnings("youtube", d)[0]).toContain("Paused");
    expect(payload("tiktok", draftFrom("tiktok", true, { short_video: 3, posting_days: ["tue"], posting_times: ["19:30"] }))).not.toHaveProperty("shorts_days");
    expect(payload("youtube", yt())).toHaveProperty("shorts_times", ["12:00"]);
  });

  it("ignores junk in stored values", () => {
    const d = draftFrom("x", true, { text_post: "3", posting_days: ["Monday", "funday", "WED"], posting_times: ["8:30", "08:30", "25:00"] });
    expect(d.posting_days).toEqual(["mon", "wed"]);
    expect(d.posting_times).toEqual(["08:30"]);
    expect(d.targets.text_post).toBe(3);
  });
});
