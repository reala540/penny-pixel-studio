import type { GeneratedIdea, IdeaGeneratorConfig } from "./types";

export const WEIGHTS = { trend: 70, originality: 10, international: 10, feasibility: 5, engagement: 5 } as const;

export const SOURCES: { id: string; label: string; needs?: string }[] = [
  { id: "google_trends_rss", label: "Google Trends (daily trending searches)" },
  { id: "google_news_rss", label: "Google News" },
  { id: "hacker_news", label: "Hacker News" },
  { id: "official_feeds", label: "Official feeds (company blogs, central banks, statistics offices)" },
  { id: "reddit_rss", label: "Reddit top posts" },
  { id: "fred", label: "FRED economic data", needs: "FRED_API_KEY" },
  { id: "sec_edgar", label: "SEC filings", needs: "SEC_USER_AGENT" },
];

export const DEFAULT_IDEA_CONFIG: IdeaGeneratorConfig = {
  frequency: "manual", weekdays: [0], hour: 8, count: 10, region: "global", channels: ["ai", "money"],
  categories: [], languages: ["en"], audience: "", min_score: 0, sources: SOURCES.map((s) => s.id),
  refresh_sources: true, notify: true,
};

export const CONFIDENCE_TEXT: Record<GeneratedIdea["confidence"], string> = {
  high: "High confidence", medium: "Medium confidence", low: "Low confidence", unverified: "Trend unverified",
};

export const SENSITIVITY_TEXT: Record<GeneratedIdea["sensitivity"], string> = {
  none: "", sensitive: "Sensitive topic", controversial: "Controversial", poorly_supported: "Poorly supported",
};

/** Points each criterion contributed (out of its weight). */
export function scoreBreakdown(idea: Pick<GeneratedIdea, "scores">): { key: keyof typeof WEIGHTS; label: string; points: number; max: number }[] {
  const label: Record<keyof typeof WEIGHTS, string> = {
    trend: "Current trend evidence", originality: "Originality", international: "International relevance",
    feasibility: "Production feasibility", engagement: "Engagement potential",
  };
  return (Object.keys(WEIGHTS) as (keyof typeof WEIGHTS)[]).map((k) => ({
    key: k, label: label[k], max: WEIGHTS[k], points: Math.round(WEIGHTS[k] * Number(idea.scores?.[k] ?? 0) * 10) / 10,
  }));
}

const clip = (t: string, n: number) => (t.length > n ? t.slice(0, n - 1).trimEnd() + "…" : t);

/** A complete, editable "Direct the studio" objective within the composer's 2,000 characters.
 *  Descriptions are trimmed first; the evidence caveat and the approval requirement are never cut. */
export function buildObjective(idea: GeneratedIdea, limit = 2000): string {
  const channel = idea.channel_slug === "ai" ? "Pixel · AI" : idea.channel_slug === "money" ? "Penny · Money" : "either channel";
  const evidence = idea.trend_signals.slice(0, 4).map((s) => {
    const when = (s.published_at ?? s.retrieved_at).slice(0, 10);
    return `- ${clip(s.title, 120)} (${s.publisher ?? s.adapter}, ${when}): ${clip(s.url, 240)}`;
  });
  const required = [
    idea.sensitivity !== "none" ? `Care needed: ${clip(idea.sensitivity_note || SENSITIVITY_TEXT[idea.sensitivity], 200)}.` : "",
    "Requirements: every factual claim must be supported by a source; no invented statistics; I will review and approve before anything is published.",
  ].filter(Boolean);
  const build = (summary: number, execution: number, ev: string[]) => [
    `Make a ${clip(idea.suggested_format || "video", 60)} for ${channel}: "${clip(idea.title, 140)}".`,
    `Summary: ${clip(idea.summary, summary)}`,
    `Audience: ${clip(idea.audience, 200)}${idea.markets.length ? `. Markets: ${idea.markets.slice(0, 8).join(", ")}` : ""}.`,
    idea.execution && execution > 0 ? `Creative direction: ${clip(idea.execution, execution)}` : "",
    idea.trend_verified ? `Why now (verify each claim against these sources):\n${ev.join("\n")}`
      : "Trend unverified: treat this as an evergreen topic and do not present it as news.",
    ...required,
  ].filter(Boolean).join("\n\n");
  for (const [summary, execution, n] of [[600, 500, 4], [400, 300, 3], [250, 150, 2], [150, 0, 1]] as const) {
    const text = build(summary, execution, evidence.slice(0, n));
    if (text.length <= limit) return text;
  }
  return build(80, 0, evidence.slice(0, 1)).slice(0, limit);
}

export function cleanCategories(raw: string): string[] {
  return raw.split(/[,\n]/).map((s) => s.trim()).filter(Boolean).slice(0, 10).map((s) => s.slice(0, 60));
}

export function cleanRegions(raw: string): "global" | string[] {
  const codes = raw.split(/[,\s]+/).map((s) => s.trim().toUpperCase()).filter((s) => /^[A-Z]{2}$/.test(s)).slice(0, 8);
  return codes.length ? codes : "global";
}
