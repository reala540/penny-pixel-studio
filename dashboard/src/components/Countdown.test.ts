import { describe, expect, it } from "vitest";
import { timeLeft } from "./Countdown";

describe("time left until a post", () => {
  const now = new Date("2026-10-27T13:04:00Z");
  const at = (mins: number) => new Date(now.getTime() + mins * 60_000);
  it("days, hours and minutes", () => {
    expect(timeLeft(at(8 * 60 + 26), now)).toBe("in 8 h 26 min");
    expect(timeLeft(at(60), now)).toBe("in 1 h");
    expect(timeLeft(at(45), now)).toBe("in 45 min");
    expect(timeLeft(at(6 * 1440 + 9 * 60 + 30), now)).toBe("in 6 days 9 h");
    expect(timeLeft(at(1440), now)).toBe("in 1 day");
  });
  it("the last minute and after the time", () => {
    expect(timeLeft(new Date(now.getTime() + 30_000), now)).toBe("in under a minute");
    expect(timeLeft(now, now)).toBe("posting now");
    expect(timeLeft(at(-5), now)).toBe("posting now");
  });
});
