// The Activity page: one plain-language timeline built from jobs, notifications and the audit log.
import { useQuery } from "@tanstack/react-query";
import { must } from "./api";
import { supabase } from "./supabase";

export type Category = "ideas" | "research" | "production" | "review" | "posting" | "settings";
export type Tone = "good" | "bad" | "info";

export interface JobRow {
  project_id?: string | null; cancel_requested_at?: string | null;
  id: string; job_type: string; status: string; progress: { label?: string; step?: number | null; total?: number | null } | null;
  input: Record<string, unknown> | null; error_message: string | null; requested_by: string;
  created_at: string; started_at: string | null; finished_at: string | null; updated_at: string;
  content_projects?: { title: string } | null;
}
export interface NoteRow { id: string; kind: string; title: string; body: string | null; link: string | null; created_at: string; error: string | null }
export interface AuditRow { id: number; actor: string; action: string; details: Record<string, unknown> | null; created_at: string }

export interface Item {
  id: string; at: string; category: Category; tone: Tone; title: string; detail?: string; link?: string | null; error?: boolean; deliveryError?: string;
}

/** The work a person thinks of as "a job" (not the internal stages inside one). */
export const JOB_LABEL: Record<string, string> = {
  generate_ideas: "Generating ideas", refine_idea: "Refining an idea", run_research: "Researching topics",
  weekly_research: "Weekly research", run_production: "Making this week's videos", weekly_production: "Weekly video production",
  run_mission: "Running your mission", regenerate_script: "Rewriting a script", rerender_preview: "Rebuilding a preview video",
  regenerate_thumbnails: "Making new thumbnails", recheck_project: "Re-checking facts", auto_review: "Automatic review",
  produce_idea: "Making a package", check_providers: "Testing the AI keys",
};

const JOB_CATEGORY: Record<string, Category> = {
  generate_ideas: "ideas", refine_idea: "ideas", run_research: "research", weekly_research: "research",
  run_production: "production", weekly_production: "production", run_mission: "production", regenerate_script: "production",
  rerender_preview: "production", regenerate_thumbnails: "production", recheck_project: "review", auto_review: "review",
  produce_idea: "production", check_providers: "production",
};

const NOTE_CATEGORY: Record<string, Category> = {
  ideas_ready: "ideas", week_ready: "production", auto_approved: "review", auto_review_needs_you: "review", auto_fixing: "review",
  published: "posting", publish_blocked: "posting", publish_ambiguous: "posting", manual_task: "posting", expired: "posting",
  job_failed: "production", token: "posting", package_ready: "review",
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

type JobLike = { job_type: string; project_id?: string | null; input?: any; updated_at: string };
const sameWork = (j: JobLike) => [j.job_type, j.project_id ?? "", j.input?.content_idea_id ?? j.input?.generated_idea_id ?? ""].join("|");

/** Failures a later run of the same job (same package or idea) has since fixed don't need anyone any more. */
export function stillFailing<T extends JobLike>(failed: T[], finished: JobLike[]): T[] {
  return failed.filter((f) => !finished.some((d) => sameWork(d) === sameWork(f) && d.updated_at > f.updated_at));
}

export function jobTitle(j: JobRow): string {
  const base = JOB_LABEL[j.job_type] ?? j.job_type.replace(/_/g, " ");
  const what = j.content_projects?.title;
  const auto = j.input?.auto_fix ? " (automatic fix)" : "";
  return `${base}${what ? `: ${what}` : ""}${auto}`;
}

export function buildTimeline(jobs: JobRow[], notes: NoteRow[], audits: AuditRow[]): Item[] {
  const items: Item[] = [];
  for (const j of jobs) {
    if (!isTopJob(j) || !["completed", "failed", "cancelled", "blocked", "needs_review"].includes(j.status)) continue;  // cancelled ones were your choice: no noise
    const failed = ["failed", "blocked", "needs_review"].includes(j.status);
    items.push({
      id: `job:${j.id}`, at: j.finished_at ?? j.updated_at, category: JOB_CATEGORY[j.job_type] ?? "production",
      tone: failed ? "bad" : "info", error: failed,
      title: `${jobTitle(j)}: ${j.status === "cancelled" ? "cancelled" : failed ? "needs attention" : "finished"}`,
      detail: failed ? (j.error_message ?? "").slice(0, 300) : undefined,
      link: jobDestination(j),
    });
  }
  for (const n of notes) {
    const bad = BAD_NOTES.has(n.kind);
    items.push({
      id: `note:${n.id}`, at: n.created_at, category: NOTE_CATEGORY[n.kind] ?? "production",
      tone: bad ? "bad" : n.kind === "published" || n.kind === "auto_approved" ? "good" : "info", error: bad,
      title: n.title, detail: n.body ?? undefined, link: n.link,
      deliveryError: n.error && n.error !== "telegram not configured" ? n.error : undefined,
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
      .select("*, content_projects(title)")
      .in("status", ["running", "queued"]).in("job_type", TOP).order("created_at").limit(20))) as unknown as JobRow[],
  });
}

/** One routing rule for status cards and the sidebar. Opening a destination never starts work. */
export function jobDestination(j: Pick<JobRow, "id" | "job_type" | "input" | "project_id" | "status">): string {
  if (j.job_type === "check_providers") return `/settings/ai?job=${encodeURIComponent(j.id)}#key-check`;
  const idea = j.input?.generated_idea_id ?? j.input?.content_idea_id;
  if (j.job_type === "produce_idea" && typeof idea === "string") {
    const p = new URLSearchParams({ step: "progress", kind: j.input?.generated_idea_id ? "generated" : "research", id: idea });
    if (j.input?.channel === "ai" || j.input?.channel === "money") p.set("channel", j.input.channel);
    return `/create?${p}`;
  }
  const pid = j.project_id ?? j.input?.project_id;
  if (typeof pid === "string") return `/content/${encodeURIComponent(pid)}`;
  return `/activity?job=${encodeURIComponent(j.id)}#job-detail`;
}
