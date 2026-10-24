import { describe, expect, it } from "vitest";
import { buildObjective, cleanCategories, cleanRegions, scoreBreakdown, WEIGHTS } from "./ideas";
import type { GeneratedIdea } from "./types";

const idea = (over: Partial<GeneratedIdea> = {}): GeneratedIdea => ({
  id: "i1", run_id: "r1", rank: 1, title: "Browser agents, tested", summary: "We time five tasks.", audience: "Office workers",
  markets: ["Global"], channel_slug: "ai", category: "AI tools", newest_evidence_at: null,
  trend_signals: [{ source_id: "s1", label: "E1", title: "Agents arrive", url: "https://example.org/a", publisher: "Reuters",
    adapter: "google_news_rss", observed: "News coverage: Reuters", published_at: "2026-10-23T09:00:00Z", retrieved_at: "2026-10-23T10:00:00Z" }],
  trend_verified: true, scores: { trend: 0.9, originality: 0.7, international: 0.6, feasibility: 0.8, engagement: 0.7 },
  total: 63 + 7 + 6 + 4 + 3.5, score_explanation: "", assessment_notes: {}, confidence: "high", sensitivity: "none",
  sensitivity_note: null, suggested_format: "long video", execution: "Timed screen demos", generated_by: "a/b", assessed_by: "c/d",
  status: "new", status_history: [], owner_note: null, created_at: "2026-10-24T00:00:00Z", ...over,
});

describe("ideas", () => {
  it("weights trend at 70 of 100", () => {
    expect(Object.values(WEIGHTS).reduce((a, b) => a + b, 0)).toBe(100);
    const parts = scoreBreakdown(idea());
    expect(parts[0]).toMatchObject({ key: "trend", max: 70, points: 63 });
    expect(parts.reduce((a, p) => a + p.points, 0)).toBeCloseTo(idea().total, 1);
  });

  it("turns an idea into an editable studio objective with evidence and the approval rule", () => {
    const text = buildObjective(idea());
    expect(text).toContain('"Browser agents, tested"');
    expect(text).toContain("https://example.org/a");
    expect(text).toContain("Reuters, 2026-10-23");
    expect(text).toContain("approve before anything is published");
    expect(text.length).toBeLessThanOrEqual(2000);
  });

  it("never presents an unverified idea as news, and stays within the limit", () => {
    const text = buildObjective(idea({ trend_verified: false, trend_signals: [], summary: "x".repeat(3000), execution: "y".repeat(3000) }));
    expect(text).toContain("Trend unverified");
    expect(text).not.toContain("Why now");
    expect(text).toContain("approve before anything is published");   // never trimmed away
    expect(text.length).toBeLessThanOrEqual(2000);
  });

  it("cleans owner input", () => {
    expect(cleanCategories("AI tools, personal finance,\n ,careers")).toEqual(["AI tools", "personal finance", "careers"]);
    expect(cleanRegions("us, ke gbr x")).toEqual(["US", "KE"]);
    expect(cleanRegions("")).toBe("global");
  });
});
