export type Channel = "ai" | "money";
export type Platform = "youtube" | "facebook" | "tiktok" | "x";

export interface Account {
  id: string;
  platform: Platform;
  label: string;
  handle: string | null;
  enabled: boolean;
  topic_mix: Record<string, number>;
  weekly_targets: Record<string, unknown>;
  oauth_connections?: { status: string; last_error: string | null; token_expires_at: string | null; app_publish_mode: string } | null;
}

/** One result of the checks, by kind: blocker (factual, can't go out like this), warning (editorial), missing (a part
 *  that wasn't made) or info (what the studio changed or noticed). */
export interface Finding { kind: "blocker" | "warning" | "missing" | "info"; code: string; text: string; detail?: string }

export interface Scene {
  narration: string;
  on_screen_text?: string | null;
  visual: { type: string; animation?: string | null; headline?: string | null; items?: string[]; stat_value?: string | null; stat_label?: string | null; chart?: unknown; stock_query?: string | null };
  claim_keys?: string[];
}

export interface ScriptBody {
  title: string;
  hook: string;
  promise?: string;
  scenes: Scene[];
  cta?: string;
  caption?: string;
  hashtags?: string[];
  claims?: { key: string; text: string; kind: string; fact_refs: string[] }[];
}

export interface Project {
  id: string;
  channel_slug: Channel;
  format: "long" | "short";
  parent_project_id: string | null;
  title: string;
  status: string;
  batch_week: string | null;
  current_script_version_id: string | null;
  quality_report: { issues?: string[]; critic?: Record<string, number>; package_problems?: string[]; duration_seconds?: number; note?: string; owner_edited?: boolean;
    findings?: Finding[]; repairs?: string[]; repaired_from_version?: number;
    shorts_remakes?: { at: string; made: number; problems?: string[] }[] };
  recipe: { preview_key?: string; preview_seconds?: number; package?: Record<string, any>;
    render?: { scenes?: { visual?: { type?: string; fallback_reason?: string } }[] };
    scene_previews?: Record<string, { key: string; version: string; seconds?: number }> };
  fresh_until: string | null;
  created_at: string;
  updated_at: string;
}

export interface Variant {
  id: string;
  project_id: string;
  social_account_id: string;
  kind: string;
  title: string | null;
  body: string | null;
  tags: string[];
  hashtags: string[];
  status: string;
  social_accounts?: { label: string; platform: Platform };
  scheduled_posts?: { id: string; scheduled_at: string; status: string }[];
}

export interface Claim {
  id: string;
  claim_key: string;
  claim_text: string;
  status: string;
  confidence: number;
  checker_notes: string | null;
  data_period: string | null;
  source_published_at: string | null;
  research_sources?: { title: string; publisher: string | null; url: string } | null;
}

export interface Post {
  id: string;
  scheduled_at: string;
  status: string;
  last_error: string | null;
  social_account_id: string;
  variant_id: string;
  content_variants?: { title: string | null; kind: string; body: string | null; project_id: string; content_projects?: { channel_slug: Channel; title: string } };
  social_accounts?: { label: string; platform: Platform };
  published_posts?: { url: string | null; method: string } | null;
}

export interface Idea {
  id: string;
  channel_slug: Channel;
  title: string;
  angle: string | null;
  status: string;
  score: number;
  score_breakdown: Record<string, number | string | boolean>;
  explanation: string | null;
  is_experiment: boolean;
  source_ids: string[];
  batch_week: string | null;
  created_at: string;
}

export interface TrendSignal {
  source_id: string;
  label: string;
  title: string;
  url: string;
  publisher: string | null;
  adapter: string;
  observed: string;
  published_at: string | null;
  retrieved_at: string;
}

export type IdeaStatus = "new" | "saved" | "rejected" | "sent_to_studio" | "archived";

export interface GeneratedIdea {
  id: string;
  run_id: string;
  rank: number;
  title: string;
  summary: string;
  audience: string;
  markets: string[];
  channel_slug: "ai" | "money" | "both" | null;
  category: string | null;
  trend_signals: TrendSignal[];
  trend_verified: boolean;
  newest_evidence_at: string | null;
  scores: { trend: number; originality: number; international: number; feasibility: number; engagement: number;
            trend_parts?: { independent_sources: number; newest_age_days: number | null; signal_strength: number; source_types: number } };
  total: number;
  score_explanation: string;
  assessment_notes: { rationale?: string; trend_angle?: string };
  confidence: "high" | "medium" | "low" | "unverified";
  sensitivity: "none" | "sensitive" | "controversial" | "poorly_supported";
  sensitivity_note: string | null;
  suggested_format: string | null;
  execution: string | null;
  generated_by: string | null;
  assessed_by: string | null;
  status: IdeaStatus;
  status_history: { at: string; status: string; by?: string; note?: string }[];
  owner_note: string | null;
  created_at: string;
}

export interface IdeaRun {
  id: string;
  trigger: string;
  status: "running" | "completed" | "partial" | "failed";
  requested_count: number;
  produced_count: number;
  evidence_count: number;
  notes: string[];
  error: string | null;
  started_at: string;
  finished_at: string | null;
  sources_used: Record<string, { ok: boolean; items?: number; error?: string }>;
}

export interface IdeaGeneratorConfig {
  frequency: "manual" | "daily" | "weekly" | "custom";
  weekdays: number[];
  hour: number;
  count: number;
  region: "global" | string[];
  channels: ("ai" | "money")[];
  categories: string[];
  languages: string[];
  audience: string;
  min_score: number;
  sources: string[];
  refresh_sources: boolean;
  notify: boolean;
}
