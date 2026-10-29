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
    expect(claimProblems([{ status: "contradicted" }, { status: "unsupported" }, { status: "unsupported" }, { status: "supported" }, { status: "stale" }]))
      .toEqual({ contradicted: 1, unsupported: 2, stale: 1 });
  });
});

describe("checks and approval are two separate answers", () => {
  it("passed checks and approval are never the same word", async () => {
    const { checkState, ownerState, reasonNeeded, includedPosts } = await import("./packageParts");
    expect(checkState([{ status: "ready_for_review" }], 0, 0)).toBe("passed");
    expect(checkState([{ status: "ready_for_review" }], 1, 0)).toBe("needs_corrections");
    expect(checkState([{ status: "ready_for_review" }, { status: "needs_attention" }], 0, 0)).toBe("needs_corrections");
    expect(ownerState("scheduled")).toBe("approved");
    expect(ownerState("needs_attention")).toBe("waiting");
    // a reason is needed exactly when the database will ask for one
    expect(reasonNeeded([{ status: "ready_for_review" }], 0)).toBe(false);
    expect(reasonNeeded([{ status: "ready_for_review" }], 2)).toBe(true);
    expect(reasonNeeded([{ status: "needs_attention" }], 0)).toBe(true);
    expect(includedPosts([
      { kind: "reel", status: "ready_for_review", social_accounts: { label: "Facebook" } },
      { kind: "reel", status: "ready_for_review", social_accounts: { label: "Facebook" } },
      { kind: "text_post", status: "rejected", social_accounts: { label: "Facebook" } },
    ], { reel: "Reel", text_post: "Text post" })).toEqual(["Facebook reel ×2"]);
  });
});

describe("findings by kind", () => {
  it("shows blockers and warnings as issues, keeps missing parts and notes apart, and never lists a note as a warning", async () => {
    const { groupFindings, visibleIssues, BAD_CLAIMS } = await import("./packageParts");
    const findings = [
      { kind: "blocker" as const, code: "claim_unsupported", text: "Not backed: x" },
      { kind: "blocker" as const, code: "check", text: "Scene 2 states numbers ['9'] without a claim/source" },
      { kind: "warning" as const, code: "critic_low", text: "Editor scores below 7: {'pacing': 5}" },
      { kind: "missing" as const, code: "package_part", text: "Short 'A' dropped" },
      { kind: "info" as const, code: "package_part", text: "Title marked as UK-specific" },
    ];
    const issues = visibleIssues({ format: "long", recipe: {}, quality_report: { findings, issues: ["old style"] } });
    expect(issues).toEqual(["Scene 2 states numbers ['9'] without a claim/source", "Editor scores below 7: {'pacing': 5}"]);
    const g = groupFindings(findings);
    expect(g.missing.map((f) => f.text)).toEqual(["Short 'A' dropped"]);
    expect(g.info.map((f) => f.text)).toEqual(["Title marked as UK-specific"]);
    expect(BAD_CLAIMS).toContain("stale");
  });
});
