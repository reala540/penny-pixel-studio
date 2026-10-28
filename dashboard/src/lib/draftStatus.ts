// What the database says about each draft: the idea may be gone, the package may already exist, be being made
// or have failed. A draft is only ever a bookmark; the database decides what's true.
import { useQuery } from "@tanstack/react-query";
import { must } from "./api";
import type { CreateDraft } from "./drafts";
import { projectPath } from "./routes";
import { supabase } from "./supabase";

export type DraftState =
  | { state: "draft" }                                          // nothing started yet: continue where you left off
  | { state: "missing" }                                        // the chosen idea was deleted
  | { state: "making"; jobStatus: string }                      // a package is queued or being made
  | { state: "failed"; error: string | null; projectId: string | null }
  | { state: "done"; projectId: string; projectStatus: string } // the package exists and is ready or decided
  | { state: "cancelled" }
  | { state: "unknown" };                                       // couldn't check

export interface DraftFacts {
  ideas: Record<string, { title: string; contentIdeaId: string | null }>;   // by draft idea id
  projects: Record<string, { id: string; status: string }>;                // by content idea id
  jobs: Record<string, { status: string; error_message: string | null; project_id: string | null }>; // latest produce_idea by draft idea id
}

const READY = ["ready_for_review", "needs_attention", "approved", "scheduled", "published", "rejected", "archived"];

export function draftState(d: CreateDraft, facts: DraftFacts | undefined): DraftState {
  if (!d.ideaId) return { state: "draft" };
  if (!facts) return { state: "unknown" };
  const idea = facts.ideas[d.ideaId];
  if (!idea) return { state: "missing" };
  const project = idea.contentIdeaId ? facts.projects[idea.contentIdeaId] : undefined;
  if (project && READY.includes(project.status)) return { state: "done", projectId: project.id, projectStatus: project.status };
  const job = facts.jobs[d.ideaId];
  if (job && ["queued", "running"].includes(job.status)) return { state: "making", jobStatus: job.status };
  if (job?.status === "failed" || project?.status === "failed") return { state: "failed", error: job?.error_message ?? null, projectId: project?.id ?? job?.project_id ?? null };
  if (job?.status === "cancelled") return { state: "cancelled" };
  if (project) return { state: "making", jobStatus: "running" };
  return { state: "draft" };
}

/** The Create address for a draft, at the step it fits now. Opening it only shows things: nothing starts. */
export function draftUrl(d: CreateDraft, s: DraftState = { state: "draft" }): string {
  if (s.state === "done") return projectPath(s.projectId);
  const p = new URLSearchParams({ draft: d.id });
  let step = d.step;
  if (s.state === "missing") step = "idea";                     // choose another idea, keep the channel
  if (s.state === "making" || s.state === "failed" || s.state === "cancelled") step = "progress";
  p.set("step", step);
  if (d.channel) p.set("channel", d.channel);
  if (d.kind && d.ideaId && s.state !== "missing") { p.set("kind", d.kind); p.set("id", d.ideaId); }
  return `/create?${p}`;
}

export function draftLabel(d: CreateDraft, s: DraftState): string {
  const what = d.ideaTitle ? `"${d.ideaTitle}"` : d.own?.trim() ? `Your idea: "${d.own.trim().slice(0, 60)}${d.own.trim().length > 60 ? "…" : ""}"` : `A new ${d.channel === "ai" ? "Pixel · AI " : d.channel === "money" ? "Penny · Money " : ""}package`;
  const where = { channel: "choosing a channel", idea: "choosing an idea", research: "checking the research", package: "ready to create the package", progress: "being made" }[d.step];
  switch (s.state) {
    case "missing": return `${what}: that idea no longer exists. Choose another one.`;
    case "making": return `${what}: ${s.jobStatus === "queued" ? "waiting to start" : "being made"}.`;
    case "cancelled": return `${what}: cancelled. Saved work is kept; you can resume it.`;
    case "failed": return `${what}: a step didn't work.`;
    case "done": return `${what}: the package is made.`;
    case "unknown": return `${what}: ${where} (couldn't check its current state).`;
    default: return `${what}: ${where}.`;
  }
}

const JOB_PAGE = 200;

/** One query for all drafts. */
export function useDraftFacts(drafts: CreateDraft[]) {
  const gen = drafts.filter((d) => d.kind === "generated" && d.ideaId).map((d) => d.ideaId!);
  const res = drafts.filter((d) => d.kind === "research" && d.ideaId).map((d) => d.ideaId!);
  return useQuery({
    queryKey: ["drafts", "facts", [...gen].sort().join(","), [...res].sort().join(",")],
    enabled: gen.length + res.length > 0,
    refetchInterval: 30_000,
    queryFn: async (): Promise<DraftFacts> => {
      const ideas: DraftFacts["ideas"] = {};
      if (gen.length) for (const g of (await must(supabase.from("generated_ideas").select("id, title, content_idea_id").in("id", gen))) as any[])
        ideas[g.id] = { title: g.title, contentIdeaId: g.content_idea_id ?? null };
      if (res.length) for (const r of (await must(supabase.from("content_ideas").select("id, title").in("id", res))) as any[])
        ideas[r.id] = { title: r.title, contentIdeaId: r.id };
      const contentIds = Object.values(ideas).map((i) => i.contentIdeaId).filter(Boolean) as string[];
      const projects: DraftFacts["projects"] = {};
      if (contentIds.length) for (const p of (await must(supabase.from("content_projects").select("id, status, idea_id").in("idea_id", contentIds).is("parent_project_id", null))) as any[])
        projects[p.idea_id] = { id: p.id, status: p.status };
      const jobs: DraftFacts["jobs"] = {};
      // newest first, page by page, until every draft has its latest job (or the history ends): an older draft's job is
      // never hidden behind a fixed number of newer ones
      const want = new Set([...gen, ...res]);
      for (let page = 0; page < 25 && Object.keys(jobs).length < want.size; page++) {
        const rows = (await must(supabase.from("generation_jobs").select("status, error_message, project_id, input, created_at").eq("job_type", "produce_idea")
          .order("created_at", { ascending: false }).range(page * JOB_PAGE, page * JOB_PAGE + JOB_PAGE - 1))) as any[];
        for (const j of rows) {
          const key = j.input?.generated_idea_id ?? j.input?.content_idea_id;
          if (key && !jobs[key] && want.has(key)) jobs[key] = { status: j.status, error_message: j.error_message, project_id: j.project_id };
        }
        if (rows.length < JOB_PAGE) break;
      }
      return { ideas, projects, jobs };
    },
  });
}
