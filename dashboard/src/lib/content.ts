// Content: packages grouped by what they need, real production progress, and one project's history.
import { useQuery } from "@tanstack/react-query";
import { must } from "./api";
import { supabase } from "./supabase";

export const CONTENT_TABS = [
  ["needs-you", "Needs you", ["ready_for_review", "needs_attention"]],
  ["in-progress", "In progress", ["draft", "scripting", "verifying", "rendering"]],
  ["scheduled", "Approved & scheduled", ["approved", "scheduled"]],
  ["published", "Published", ["published"]],
  ["not-used", "Not used", ["rejected", "failed", "archived"]],
  ["all", "All", null],
] as const;
export type ContentTab = (typeof CONTENT_TABS)[number][0];

export function tabStatuses(tab: string): readonly string[] | null {
  return (CONTENT_TABS.find(([k]) => k === tab) ?? CONTENT_TABS[0])[2];
}

/** Packages waiting for the owner (ready for review or needing a look): the count beside Content. */
export function useNeedsYouCount() {
  return useQuery({
    queryKey: ["needs-you-count"],
    refetchInterval: 30_000,
    queryFn: async () => {
      const { count, error } = await supabase.from("content_projects").select("id", { count: "exact", head: true })
        .in("status", ["ready_for_review", "needs_attention"]).is("parent_project_id", null);
      if (error) throw new Error(error.message);
      return count ?? 0;
    },
  });
}

// ------------------------------------------------------------------ production progress (only what the engine reports)

export const STAGES = [
  ["script", "Script written and facts checked"],
  ["package", "Shorts, titles and post texts"],
  ["render_preview", "Previews rendered"],
  ["thumbnails", "Thumbnails"],
] as const;

export interface StageJob { id: string; job_type: string; status: string; error_message: string | null; project_id: string; updated_at: string }
export type StageState = "waiting" | "running" | "done" | "failed";
export interface StageRow { key: string; label: string; state: StageState; detail?: string; error?: string }

const FAILED = new Set(["failed", "retrying", "blocked", "needs_review"]);

/** One row per real stage. Previews count one job per video and Short; nothing is invented between stages. */
export function stageRows(jobs: StageJob[]): StageRow[] {
  return STAGES.map(([key, label]) => {
    const mine = jobs.filter((j) => j.job_type === key);
    if (!mine.length) return { key, label, state: "waiting" as const };
    const bad = mine.find((j) => FAILED.has(j.status));
    const done = mine.filter((j) => j.status === "completed").length;
    const running = mine.some((j) => j.status === "running" || j.status === "pending" || j.status === "queued");
    const detail = key === "render_preview" && mine.length > 1 ? `${done} of ${mine.length} done` : undefined;
    if (bad) return { key, label, state: "failed" as const, detail, error: bad.error_message ?? "This step didn't work." };
    if (running || done < mine.length) return { key, label, state: "running" as const, detail };
    return { key, label, state: "done" as const, detail };
  });
}

export function useStageJobs(projectId: string | null | undefined, live = true) {
  return useQuery({
    queryKey: ["stage-jobs", projectId],
    enabled: Boolean(projectId),
    refetchInterval: live ? 10_000 : false,
    queryFn: async () => {
      const family = (await must(supabase.from("content_projects").select("id").or(`id.eq.${projectId},parent_project_id.eq.${projectId}`))) as { id: string }[];
      return (await must(supabase.from("generation_jobs").select("id, job_type, status, error_message, project_id, updated_at")
        .in("project_id", family.map((f) => f.id)).in("job_type", STAGES.map(([k]) => k)).order("created_at"))) as StageJob[];
    },
  });
}

// ------------------------------------------------------------------ one project's history

export interface HistoryItem { at: string; title: string; detail?: string; tone: "good" | "bad" | "info"; url?: string }

/** Built only from rows that carry this project's id (notifications only when their link names it). */
export function useProjectHistory(projectId: string) {
  return useQuery({
    queryKey: ["project-history", projectId],
    queryFn: async () => {
      const family = (await must(supabase.from("content_projects").select("id, title, format").or(`id.eq.${projectId},parent_project_id.eq.${projectId}`))) as { id: string; title: string; format: string }[];
      const ids = family.map((f) => f.id);
      const name = (id: string) => (id === projectId ? "Video" : `Short: ${family.find((f) => f.id === id)?.title ?? ""}`);
      const [jobs, reviews, approvals, variants, notes] = await Promise.all([
        must(supabase.from("generation_jobs").select("job_type, status, error_message, project_id, updated_at").in("project_id", ids).order("updated_at", { ascending: false }).limit(80)),
        must(supabase.from("auto_reviews").select("verdict, attempt, fix, reasons, created_at").eq("project_id", projectId).order("created_at", { ascending: false })),
        must(supabase.from("approvals").select("decision, source, notes, decided_at, target_type, target_id").in("target_id", ids)),
        must(supabase.from("content_variants").select("id, kind, social_accounts(label), scheduled_posts(status, scheduled_at, updated_at, published_posts(url, published_at))").in("project_id", ids)),
        must(supabase.from("notifications").select("title, body, created_at, link").like("link", `%${projectId}%`).order("created_at", { ascending: false }).limit(20)),
      ]);
      const items: HistoryItem[] = [];
      for (const j of jobs as any[]) {
        if (!["completed", "failed", "retrying", "blocked", "needs_review"].includes(j.status)) continue;
        const ok = j.status === "completed";
        items.push({ at: j.updated_at, tone: ok ? "info" : "bad", title: `${name(j.project_id)}: ${JOB_TEXT[j.job_type] ?? j.job_type.replace(/_/g, " ")} ${ok ? "finished" : "didn't work"}`, detail: ok ? undefined : (j.error_message ?? "").slice(0, 240) });
      }
      for (const r of reviews as any[]) {
        items.push({ at: r.created_at, tone: r.verdict === "approved" ? "good" : r.verdict === "fixing" ? "info" : "bad",
          title: `Automatic review: ${REVIEW_TEXT[r.verdict] ?? r.verdict}${r.verdict === "fixing" ? ` (attempt ${r.attempt})` : ""}`, detail: r.fix ?? (r.reasons ?? []).slice(0, 2).join(" · ") });
      }
      for (const a of approvals as any[]) {
        if (a.target_type !== "project" || a.target_id !== projectId) continue;
        items.push({ at: a.decided_at, tone: a.decision === "approved" ? "good" : "bad", title: `${a.decision === "approved" ? "Approved" : a.decision === "rejected" ? "Discarded" : a.decision} ${a.source === "auto_review" ? "by Auto Review & Post" : "by you"}`, detail: a.notes ?? undefined });
      }
      for (const v of variants as any[]) {
        for (const p of v.scheduled_posts ?? []) {
          const pub = Array.isArray(p.published_posts) ? p.published_posts[0] : p.published_posts;
          if (pub) items.push({ at: pub.published_at, tone: "good", title: `Published on ${v.social_accounts?.label ?? "an account"}`, url: pub.url ?? undefined });
          else if (["failed", "blocked", "needs_review", "needs_manual", "cancelled"].includes(p.status)) items.push({ at: p.updated_at, tone: p.status === "cancelled" ? "info" : "bad", title: `${v.social_accounts?.label ?? "Post"}: ${POST_TEXT[p.status]}` });
        }
      }
      for (const n of notes as any[]) items.push({ at: n.created_at, tone: "info", title: n.title, detail: n.body ?? undefined });
      return items.sort((x, y) => Date.parse(y.at) - Date.parse(x.at));
    },
  });
}

const JOB_TEXT: Record<string, string> = { script: "writing and fact check", package: "Shorts and posts", render_preview: "preview", thumbnails: "thumbnails",
  regenerate_script: "rewrite", rerender_preview: "re-render", regenerate_thumbnails: "new thumbnails", recheck_project: "fact re-check", produce_idea: "package request",
  remake_shorts: "new Shorts" };
const REVIEW_TEXT: Record<string, string> = { approved: "approved", needs_review: "sent to you", error: "couldn't check, sent to you", skipped: "skipped", fixing: "fixing" };
const POST_TEXT: Record<string, string> = { failed: "didn't post", blocked: "on hold (facts need a re-check)", needs_review: "check on the platform", needs_manual: "post it yourself", cancelled: "cancelled" };
