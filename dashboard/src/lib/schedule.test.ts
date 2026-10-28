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

  it("Facebook Stories follow their Reels three hours later; long videos take a slot", () => {
    const fb = draftFrom("facebook", true, { reel: 2, story: 2, text_post: 1, long_video: 1,
      posting_days: ["mon", "wed", "fri", "sat"], posting_times: ["19:00", "22:30"] });
    const week = weekPreview("facebook", fb);
    expect(week.mon).toEqual([{ time: "19:00", label: "Reels" }, { time: "22:00", label: "Story" }, { time: "22:30", label: "Reels" }]);
    expect(week.tue).toEqual([{ time: "01:30", label: "Story" }]);           // past midnight: the next day
    expect(week.wed).toEqual([{ time: "19:00", label: "Text posts" }, { time: "22:30", label: "Long videos" }]);
    expect(totalPerWeek("facebook", fb)).toBe(6);
    expect(warnings("facebook", fb)).toEqual([]);
    const more = draftFrom("facebook", true, { reel: 1, story: 3, posting_days: ["mon"], posting_times: ["19:00"] });
    expect(warnings("facebook", more).join(" ")).toContain("only 1 Story will be posted");
  });

  it("a never-saved post type left at 0 isn't sent, so older databases still save", () => {
    const saved = { reel: 3, text_post: 2, posting_days: ["mon"], posting_times: ["19:00"] };
    const fb = draftFrom("facebook", true, saved);
    expect(payload("facebook", fb, saved).targets).toEqual({ reel: 3, text_post: 2 });
    expect(payload("facebook", { ...fb, targets: { ...fb.targets, story: 2 } }, saved).targets).toEqual({ reel: 3, text_post: 2, story: 2 });
    expect(payload("facebook", { ...fb, targets: { ...fb.targets, reel: 0 } }, saved).targets).toEqual({ reel: 0, text_post: 2 });
  });
});

describe("Facebook Reels and text posts on their own times", () => {
  const base = { reel: 2, text_post: 1, posting_days: ["mon", "wed", "fri"], posting_times: ["12:30"] };
  it("without their own times they share the Page's slots, as before", () => {
    const week = weekPreview("facebook", draftFrom("facebook", true, base));
    expect([week.mon[0].label, week.wed[0].label, week.fri[0].label]).toEqual(["Reels", "Reels", "Text posts"]);
  });
  it("with their own times each goes on its own days and times", () => {
    const d = draftFrom("facebook", true, { ...base, reel_days: ["sat", "sun"], reel_times: ["19:00"], text_days: ["tue"], text_times: ["08:00"] });
    const week = weekPreview("facebook", d);
    expect(week.sat).toEqual([{ time: "19:00", label: "Reels" }]);
    expect(week.sun).toEqual([{ time: "19:00", label: "Reels" }]);
    expect(week.tue).toEqual([{ time: "08:00", label: "Text posts" }]);
    expect(week.mon).toEqual([]);
    expect(payload("facebook", d)).toMatchObject({ reel_days: ["sat", "sun"], reel_times: ["19:00"], text_days: ["tue"] });
    expect(warnings("facebook", { ...d, reel_times: [] }).some((m) => m.includes("Reel"))).toBe(false); // half-set falls back
  });
  it("warns when Reels and text posts land too close together", () => {
    const d = draftFrom("facebook", true, { reel: 1, text_post: 1, reel_days: ["mon"], reel_times: ["12:00"], text_days: ["mon"], text_times: ["12:30"],
      posting_days: ["fri"], posting_times: ["09:00"] });
    expect(warnings("facebook", d).some((m) => m.includes("less than an hour apart"))).toBe(true);
  });
  it("says how much of the week is covered, and why not", async () => {
    const { coverage } = await import("./schedule");
    const d = draftFrom("facebook", true, base);
    const rows = coverage("facebook", d, [{ kind: "text_post", approved: true }]);
    expect(rows.find((r) => r.kind === "reel")).toMatchObject({ target: 2, scheduled: 0, gap: 2, cause: "not enough short videos made and approved yet" });
    expect(rows.find((r) => r.kind === "text_post")).toMatchObject({ scheduled: 1, gap: 0 });
    const few = coverage("x", draftFrom("x", true, { text_post: 5, posting_days: ["mon"], posting_times: ["09:00"] }), []);
    expect(few[0].cause).toBe("only 1 slot a week for them");
  });
});
