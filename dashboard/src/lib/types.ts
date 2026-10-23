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

export interface Scene {
  narration: string;
  on_screen_text?: string | null;
  visual: { type: string; headline?: string | null; items?: string[]; stat_value?: string | null; stat_label?: string | null; chart?: unknown; stock_query?: string | null };
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
  quality_report: { issues?: string[]; critic?: Record<string, number>; package_problems?: string[]; duration_seconds?: number; note?: string; owner_edited?: boolean };
  recipe: { preview_key?: string; preview_seconds?: number; package?: Record<string, any> };
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
