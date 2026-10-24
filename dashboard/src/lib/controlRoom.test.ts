import { describe, expect, it } from "vitest";
import { compact, embedTitle, jobLabel, relativeTime, workflowLabel } from "./controlRoom";

describe("Mission Control formatting", () => {
  it("formats recent activity and clamps future clock skew", () => {
    const now = Date.parse("2026-10-24T12:00:00Z");
    expect(relativeTime("2026-10-24T11:59:40Z", now)).toBe("20s ago");
    expect(relativeTime("2026-10-24T11:45:00Z", now)).toBe("15m ago");
    expect(relativeTime("2026-10-24T09:00:00Z", now)).toBe("3h ago");
    expect(relativeTime("2026-10-24T12:00:01Z", now)).toBe("0s ago");
  });

  it("formats token counts and operator-facing job names", () => {
    expect(compact(999)).toBe("999");
    expect(compact(1250)).toBe("1.3k");
    expect(jobLabel("run_research")).toBe("Research");
    expect(jobLabel("render_preview")).toBe("Render preview");
    expect(workflowLabel("produce")).toBe("Production");
  });

  it("reads a linked project title in either embed shape", () => {
    expect(embedTitle({ title: "One" })).toBe("One");
    expect(embedTitle([{ title: "Two" }])).toBe("Two");
    expect(embedTitle(null)).toBeUndefined();
  });
});
