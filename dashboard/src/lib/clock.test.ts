import { describe, expect, it } from "vitest";
import { clockFace, isValidZone, KENYA_TZ, placeName } from "./clock";

describe("header clocks", () => {
  it("one instant, two zones", () => {
    const t = new Date("2026-11-02T22:30:05Z");
    expect(clockFace(t, "America/New_York")).toMatchObject({ time: "17:30:05", date: "Mon 2 Nov", zone: "EST" });
    expect(clockFace(t, KENYA_TZ)).toMatchObject({ time: "01:30:05", date: "Tue 3 Nov", zone: "GMT+3" });  // the date rolls over
    expect(clockFace(t, KENYA_TZ).iso).toBe(clockFace(t, "America/New_York").iso);
  });

  it("follows daylight saving; Kenya has none", () => {
    // New York leaves daylight saving at 06:00 UTC on 1 Nov 2026
    expect(clockFace(new Date("2026-11-01T05:59:59Z"), "America/New_York")).toMatchObject({ time: "01:59:59", zone: "EDT" });
    expect(clockFace(new Date("2026-11-01T06:00:00Z"), "America/New_York")).toMatchObject({ time: "01:00:00", zone: "EST" });
    expect(clockFace(new Date("2026-07-01T12:00:00Z"), KENYA_TZ).time).toBe("15:00:00");
    expect(clockFace(new Date("2026-01-01T12:00:00Z"), KENYA_TZ).time).toBe("15:00:00");
  });

  it("midnight and year rollover", () => {
    expect(clockFace(new Date("2026-12-31T20:59:59Z"), KENYA_TZ)).toMatchObject({ time: "23:59:59", date: "Thu 31 Dec" });
    expect(clockFace(new Date("2026-12-31T21:00:00Z"), KENYA_TZ)).toMatchObject({ time: "00:00:00", date: "Fri 1 Jan" });
  });

  it("an unknown or empty zone is refused, never replaced", () => {
    expect(isValidZone("Mars/Base")).toBe(false);
    expect(isValidZone("")).toBe(false);
    expect(isValidZone(42)).toBe(false);
    expect(isValidZone("Australia/Sydney")).toBe(true);
    expect(() => clockFace(new Date(), "Mars/Base")).toThrow(RangeError);
  });

  it("place names", () => {
    expect(placeName("America/New_York")).toBe("New York");
    expect(placeName("Africa/Nairobi")).toBe("Nairobi");
  });
});
