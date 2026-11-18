import { describe, expect, it } from "vitest";
import { checksOff } from "./PostWithoutChecks";

describe("post without last-minute checks (same rule as the engine)", () => {
  const now = new Date("2026-11-18T10:00:00Z");
  it("is off when missing or switched off", () => {
    expect(checksOff(null, now)).toBe(false);
    expect(checksOff({ on: false }, now)).toBe(false);
    expect(checksOff("yes", now)).toBe(false);
  });
  it("is on with no end time", () => {
    expect(checksOff(true, now)).toBe(true);
    expect(checksOff({ on: true }, now)).toBe(true);
  });
  it("respects an end time", () => {
    expect(checksOff({ on: true, until: "2026-11-19T00:00:00Z" }, now)).toBe(true);
    expect(checksOff({ on: true, until: "2026-11-16T21:00:00Z" }, now)).toBe(false);
    expect(checksOff({ on: true, until: "not a date" }, now)).toBe(false);
  });
});
