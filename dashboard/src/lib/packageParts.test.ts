import { describe, expect, it } from "vitest";
import { claimProblems, droppedShorts, visibleIssues } from "./packageParts";

const qr = {
  issues: ["Too short: about 7.8 min (aim for 8-14 min)", "Critic score below 7: {'hook': 6}"],
  package_problems: [
    "Short 'AI Adoption' dropped: ['Short too thin: ~11s', 'Sentences too long on average (35.0 words)']",
    "Short 'AI ROI' dropped: ['Short too thin: ~12s', 'Sentences too long on average (40.0 words)']",
  ],
};

describe("package parts", () => {
  it("reads why each Short was dropped", () => {
    expect(droppedShorts(qr)).toEqual([
      { title: "AI Adoption", reasons: ["Short too thin: ~11s", "Sentences too long on average (35.0 words)"] },
      { title: "AI ROI", reasons: ["Short too thin: ~12s", "Sentences too long on average (40.0 words)"] },
    ]);
    expect(droppedShorts({ shorts_remakes: [{ at: "x", made: 0, problems: ["Retry 1: Short 'Again' dropped: ['Short too thin: ~9s']"] }] }))
      .toEqual([{ title: "Again", reasons: ["Short too thin: ~9s"] }]);
    expect(droppedShorts({})).toEqual([]);
  });
  it("uses the real video length, and lists dropped Shorts only in Short videos", () => {
    const long = { format: "long" as const, quality_report: qr, recipe: { preview_seconds: 582.6 } };
    expect(visibleIssues(long)).toEqual(["Critic score below 7: {'hook': 6}"]);
    expect(visibleIssues({ ...long, recipe: { preview_seconds: 300 } })[0]).toMatch(/^Too short/);
  });
  it("counts contradicted and unsupported claims", () => {
    expect(claimProblems([{ status: "contradicted" }, { status: "unsupported" }, { status: "unsupported" }, { status: "supported" }]))
      .toEqual({ contradicted: 1, unsupported: 2 });
  });
});
