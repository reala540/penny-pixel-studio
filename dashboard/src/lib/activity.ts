// The Activity page: one plain-language timeline built from jobs, notifications and the audit log.
import { useQuery } from "@tanstack/react-query";
import { must } from "./api";
import { supabase } from "./supabase";

export type Category = "ideas" | "research" | "production" | "review" | "posting" | "settings";
export type Tone = "good" | "bad" | "info";

export interface JobRow {
  id: string; job_type: string; status: string; progress: { label?: string; step?: number | null; total?: number | null } | null;
  input: Record<string, unknown> | null; error_message: string | null; requested_by: string;
  created_at: string; started_at: string | null; finished_at: string | null; updated_at: string;
  content_projects?: { title: string } | null;
}
export interface NoteRow { id: string; kind: string; title: string; body: string | null; link: string | null; created_at: string; error: string | null }
export interface AuditRow { id: number; actor: string; action: string; details: Record<string, unknown> | null; created_at: string }

export interface Item {
  id: string; at: string; category: Category; tone: Tone; title: string; detail?: string; link?: string | null; error?: boolean;
}

/** The work a person thinks of as "a job" (not the internal stages inside one). */
export const JOB_LABEL: Record<string, string> = {
  generate_ideas: "Generating ideas", refine_idea: "Refining an idea", run_research: "Researching topics",
  weekly_research: "Weekly research", run_production: "Making this week's videos", weekly_production: "Weekly video production",
  run_mission: "Running your mission", regenerate_script: "Rewriting a script", rerender_preview: "Rebuilding a preview video",
  regenerate_thumbnails: "Making new thumbnails", recheck_project: "Re-checking facts", auto_review: "Automatic review",
};

const JOB_CATEGORY: Record<string, Category> = {
  generate_ideas: "ideas", refine_idea: "ideas", run_research: "research", weekly_research: "research",
  run_production: "production", weekly_production: "production", run_mission: "production", regenerate_script: "production",
  rerender_preview: "production", regenerate_thumbnails: "production", recheck_project: "review", auto_review: "review",
};

const NOTE_CATEGORY: Record<string, Category> = {
  ideas_ready: "ideas", week_ready: "production", auto_approved: "review", auto_review_needs_you: "review", auto_fixing: "review",
  published: "posting", publish_blocked: "posting", publish_ambiguous: "posting", manual_task: "posting", expired: "posting",
  job_failed: "production", token: "posting",
};
const BAD_NOTES = new Set(["publish_blocked", "publish_ambiguous", "job_failed", "token", "expired"]);

const AUDIT_TEXT: Record<string, (d: Record<string, unknown>) => string> = {
  auto_review_post_on: () => "Auto Review & Post switched ON",
  auto_review_post_off: (d) => `Auto Review & Post switched OFF${d.reverted_posts ? ` (${d.reverted_posts} post(s) back in Review)` : ""}`,
  posting_schedule_changed: (d) => `Posting schedule changed for ${d.account ?? "an account"}${d.moved_posts ? ` (${d.moved_posts} post(s) moved)` : ""}`,
  setup_value_saved: (d) => `Setup: ${d.name} saved`,
  setup_value_removed: (d) => `Setup: ${d.name} removed (GitHub value used again)`,
  paused: () => "Publishing paused", resumed: () => "Publishing resumed", telegram_linked: () => "Telegram linked",
  setting_changed: (d) => `Setting changed: ${String((d as { key?: string }).key ?? "")}`.replace(/: $/, ""),
};

export const isTopJob = (j: Pick<JobRow, "job_type">) => j.job_type in JOB_LABEL;

export function jobTitle(j: JobRow): string {
  const base = JOB_LABEL[j.job_type] ?? j.job_type.replace(/_/g, " ");
  const what = j.content_projects?.title;
  const auto = j.input?.auto_fix ? " (automatic fix)" : "";
  return `${base}${what ? `: ${what}` : ""}${auto}`;
}

export function buildTimeline(jobs: JobRow[], notes: NoteRow[], audits: AuditRow[]): Item[] {
  const items: Item[] = [];
  for (const j of jobs) {
    if (!isTopJob(j) || !["completed", "failed"].includes(j.status)) continue;  // cancelled ones were your choice: no noise
    const failed = j.status === "failed";
    items.push({
      id: `job:${j.id}`, at: j.finished_at ?? j.updated_at, category: JOB_CATEGORY[j.job_type] ?? "production",
      tone: failed ? "bad" : "info", error: failed,
      title: `${jobTitle(j)}: ${failed ? "failed" : "finished"}`,
      detail: failed ? (j.error_message ?? "").slice(0, 300) : undefined,
    });
  }
  for (const n of notes) {
    const bad = BAD_NOTES.has(n.kind);
    items.push({
      id: `note:${n.id}`, at: n.created_at, category: NOTE_CATEGORY[n.kind] ?? "production",
      tone: bad ? "bad" : n.kind === "published" || n.kind === "auto_approved" ? "good" : "info", error: bad,
      title: n.title, detail: n.body ?? undefined, link: n.link,
    });
  }
  for (const a of audits) {
    const text = AUDIT_TEXT[a.action];
    if (!text) continue;
    items.push({ id: `audit:${a.id}`, at: a.created_at, category: "settings", tone: "info", title: text(a.details ?? {}), detail: `By ${a.actor}` });
  }
  return items.sort((x, y) => Date.parse(y.at) - Date.parse(x.at));
}

export function inFilter(i: Item, f: Category | "all" | "errors"): boolean {
  return f === "all" ? true : f === "errors" ? Boolean(i.error) : i.category === f;
}

const TOP = Object.keys(JOB_LABEL);

/** Running and queued jobs, refreshed every 10 seconds (shared by the menu indicator and the Activity page). */
export function useRunningJobs() {
  return useQuery({
    queryKey: ["running-jobs"],
    refetchInterval: 10_000,
    queryFn: async () => (await must(supabase.from("generation_jobs")
      .select("id, job_type, status, progress, input, error_message, requested_by, created_at, started_at, finished_at, updated_at, content_projects(title)")
      .in("status", ["running", "queued"]).in("job_type", TOP).order("created_at").limit(20))) as unknown as JobRow[],
  });
}
