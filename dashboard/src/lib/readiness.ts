// Can the studio make content right now? Only what creation really needs counts: the database and the Worker
// (it starts every job) plus working AI services. Telegram and social accounts are for alerts and publishing.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { must, queueJob, useSetting } from "./api";
import { callWorker, supabase, workerUrl } from "./supabase";

/** Jobs a package needs, in plain words (the names used in AI services → Models and the jobs they do). */
export const PACKAGE_ROLES: [string, string][] = [
  ["research_summarizer", "Evidence scout"], ["scriptwriter", "Scriptwriter"], ["voice_editor", "Voice editor"],
  ["critic", "Critic"], ["claim_checker", "Claim checker"], ["repurposer", "Distribution editor"],
];
export const STALE_HOURS = 24;

type Check = { checked_at?: string; results?: { provider: string; status: string; model?: string; error?: string; note?: string }[] };
type Core = { core: Record<string, { ok: boolean; detail: string }> };

export interface Readiness {
  canCreate: boolean;
  blockers: { text: string; to: string }[];
  warnings: { text: string; to: string }[];
  checkedAt: string | null;
  stale: boolean;
  okProviders: string[];
  /** Jobs with no enabled model from a provider that passed the last key check. A pass doesn't prove every model works. */
  uncoveredRoles: string[];
  /** The key check or the model list failed to load (not the same as "never checked"). */
  checkError: boolean;
  aiError: boolean;
  loading: boolean;
}

export function readiness(input: { worker: boolean; core?: Core | null; coreError?: boolean; check?: Check | null;
    /** The last key check or the model list couldn't be loaded: say so, never "not checked" or "nothing covers this". */
    checkError?: boolean; aiError?: boolean;
  models?: { provider: string; roles: string[]; enabled: boolean }[]; providers?: { name: string; enabled: boolean }[]; now?: number }): Omit<Readiness, "loading"> {
  const blockers: Readiness["blockers"] = [];
  const warnings: Readiness["warnings"] = [];
  if (!input.worker) blockers.push({ text: "The Worker isn't connected, so the studio can't start any work.", to: "/settings/setup#basics" });
  if (input.core?.core?.database && !input.core.core.database.ok) blockers.push({ text: "The database can't be reached.", to: "/settings/setup#basics" });
  if (input.core?.core?.github && !input.core.core.github.ok) blockers.push({ text: "GitHub refused the Worker's token, so jobs can't start.", to: "/settings/setup#basics" });
  if (input.coreError) warnings.push({ text: "Couldn't check the Worker just now.", to: "/settings/setup#basics" });
  const results = input.check?.results ?? [];
  const okProviders = results.filter((r) => r.status === "ok").map((r) => r.provider);
  const checkedAt = input.check?.checked_at ?? null;
  const age = checkedAt ? ((input.now ?? Date.now()) - Date.parse(checkedAt)) / 3_600_000 : Infinity;
  const stale = age > STALE_HOURS;
  if (input.checkError) warnings.push({ text: "Couldn't load the last AI key check.", to: "/settings/ai" });
  else if (!checkedAt) warnings.push({ text: "The AI keys haven't been checked yet.", to: "/settings/ai" });
  else if (okProviders.length === 0) blockers.push({ text: "No AI service passed the last key check.", to: "/settings/ai" });
  if (checkedAt && stale) warnings.push({ text: `The last key check is ${Math.round(age)} hours old: results may have changed.`, to: "/settings/ai" });
  const enabled = new Set((input.providers ?? []).filter((p) => p.enabled).map((p) => p.name));
  const passing = new Set(okProviders.filter((p) => enabled.has(p)));
  const uncoveredRoles = input.aiError ? [] : PACKAGE_ROLES.filter(([role]) => !(input.models ?? []).some((m) => m.enabled && passing.has(m.provider) && m.roles.includes(role)))
    .map(([, label]) => label);
  if (input.aiError) warnings.push({ text: "Couldn't load the AI services and models.", to: "/settings/ai" });
  else if (checkedAt && okProviders.length && uncoveredRoles.length) {
    warnings.push({ text: `No service that passed the key check does these jobs: ${uncoveredRoles.join(", ")}. A package may stop at that step.`, to: "/settings/ai" });
  }
  return { canCreate: blockers.length === 0, blockers, warnings, checkedAt, stale, okProviders, uncoveredRoles,
    checkError: Boolean(input.checkError), aiError: Boolean(input.aiError) };
}

export function useReadiness(): Readiness {
  const check = useSetting<Check | null>("provider_check", null);
  const core = useQuery({
    queryKey: ["setup-status"], enabled: Boolean(workerUrl), staleTime: 5 * 60_000, retry: 0,
    queryFn: () => callWorker<Core>("/api/setup/status", {}),
  });
  const ai = useQuery({
    queryKey: ["readiness-models"],
    queryFn: async () => {
      const [models, providers] = await Promise.all([
        must(supabase.from("ai_model_configs").select("provider, roles, enabled")),
        must(supabase.from("ai_providers").select("name, enabled")),
      ]);
      return { models: models as { provider: string; roles: string[]; enabled: boolean }[], providers: providers as { name: string; enabled: boolean }[] };
    },
  });
  const r = readiness({ worker: Boolean(workerUrl), core: core.data, coreError: core.isError, check: check.data,
    checkError: check.isError, aiError: ai.isError, models: ai.data?.models, providers: ai.data?.providers });
  return { ...r, loading: check.isLoading || ai.isLoading };
}

/** "Test again": runs the same key check as First-time setup, in the queue (owner job "check_providers"). */
export function useKeyCheck() {
  const qc = useQueryClient();
  const active = useQuery({
    queryKey: ["key-check-job"],
    refetchInterval: (q) => (q.state.data ? 5000 : false),
    queryFn: async () => ((await must(supabase.from("generation_jobs").select("id, status").eq("job_type", "check_providers")
      .in("status", ["queued", "running"]).limit(1))) as { id: string; status: string }[])[0] ?? null,
  });
  const run = useMutation({
    mutationFn: () => queueJob("check_providers"),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["key-check-job"] }); },
  });
  const wasActive = Boolean(active.data);
  return { running: wasActive, run, refresh: () => qc.invalidateQueries({ queryKey: ["setting", "provider_check"] }) };
}
