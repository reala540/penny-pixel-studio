import { describe, expect, it } from "vitest";
import { localDay, moveToDay, statusTone, weekDays } from "./format";

describe("time helpers", () => {
  it("uses the owner's timezone for the local day", () => {
    // 22:30 UTC on Sunday is already Monday in Nairobi (UTC+3)
    expect(localDay("2026-10-25T22:30:00Z", "Africa/Nairobi")).toBe("2026-10-26");
  });

  it("builds a Monday-first week", () => {
    const days = weekDays(new Date("2026-10-29T10:00:00Z"), "Africa/Nairobi");
    expect(days[0]).toBe("2026-10-26");
    expect(days).toHaveLength(7);
  });

  it("moves a post to another day keeping its local time", () => {
    const moved = moveToDay("2026-10-26T15:00:00Z", "2026-10-28", "Africa/Nairobi");
    expect(moved).toBe("2026-10-28T15:00:00.000Z");
  });
});

describe("status tone", () => {
  it("marks problems as bad and waiting items as warnings", () => {
    expect(statusTone("blocked")).toBe("bad");
    expect(statusTone("needs_manual")).toBe("warn");
    expect(statusTone("published")).toBe("good");
  });
});
