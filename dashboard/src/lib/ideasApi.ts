import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { must, queueJob } from "./api";
import { supabase } from "./supabase";
import type { GeneratedIdea, IdeaRun, IdeaStatus } from "./types";

export const IDEA_SELECT = "*";

export function useActiveIdeaJob() {
  return useQuery({
    queryKey: ["idea-job"],
    refetchInterval: (q) => (q.state.data ? 5000 : 30_000),
    queryFn: async () => {
      const rows = (await must(supabase.from("generation_jobs").select("id, job_type, status, created_at")
        .in("job_type", ["generate_ideas", "refine_idea"]).in("status", ["queued", "running", "retrying"])
        .order("created_at", { ascending: false }).limit(1))) as { id: string; job_type: string; status: string }[];
      return rows[0] ?? null;
    },
  });
}

export function useIdeaRuns(limit = 10, poll = false) {
  return useQuery({
    queryKey: ["idea-runs", limit],
    refetchInterval: poll ? 5000 : false,
    queryFn: async () => (await must(supabase.from("idea_runs").select("*").order("created_at", { ascending: false }).limit(limit))) as IdeaRun[],
  });
}

export function useIdeas(filter: { runId?: string; status?: IdeaStatus | "all"; limit?: number }, poll = false) {
  return useQuery({
    queryKey: ["ideas", filter],
    enabled: filter.runId !== "",
    refetchInterval: poll ? 5000 : false,
    queryFn: async () => {
      let q = supabase.from("generated_ideas").select(IDEA_SELECT);
      if (filter.runId) q = q.eq("run_id", filter.runId).order("rank");
      else q = q.order("created_at", { ascending: false }).order("rank");
      if (filter.status && filter.status !== "all") q = q.eq("status", filter.status);
      return (await must(q.limit(filter.limit ?? 200))) as GeneratedIdea[];
    },
  });
}

export function useIdeaActions() {
  const qc = useQueryClient();
  const refresh = () => {
    qc.invalidateQueries({ queryKey: ["ideas"] });
    qc.invalidateQueries({ queryKey: ["idea-job"] });
    qc.invalidateQueries({ queryKey: ["idea-runs"] });
  };
  const setStatus = useMutation({
    mutationFn: async ({ idea, status, note }: { idea: GeneratedIdea; status: IdeaStatus; note?: string }) => {
      const history = [...(idea.status_history ?? []), { at: new Date().toISOString(), status, by: "owner", ...(note ? { note } : {}) }];
      await must(supabase.from("generated_ideas").update({ status, status_history: history }).eq("id", idea.id));
    },
    onSuccess: refresh,
  });
  const generate = useMutation({
    mutationFn: (trigger: "manual" | "regenerate") => queueJob("generate_ideas", { input: { trigger } }),
    onSuccess: refresh,
  });
  const refine = useMutation({
    mutationFn: ({ idea, note }: { idea: GeneratedIdea; note: string }) =>
      queueJob("refine_idea", { input: { idea_id: idea.id, note: note.slice(0, 800) } }),
    onSuccess: refresh,
  });
  return { setStatus, generate, refine, refresh };
}
