import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { announceChange, friendlyError } from "./state";
import { isValidZone } from "./clock";
import { callWorker, supabase } from "./supabase";
import type { Account } from "./types";

export async function must<T>(p: PromiseLike<{ data: T | null; error: { message: string } | null }>): Promise<T> {
  let res: { data: T | null; error: { message: string } | null };
  try {
    res = await p;
  } catch (e) {  // the request never reached the database (offline, DNS, blocked)
    throw new Error(friendlyError(e));
  }
  if (res.error) throw new Error(friendlyError(res.error.message));
  return res.data as T;
}

/** A setting. `fallback` is used only when the database confirms the setting isn't saved: when the request fails,
 *  `data` stays undefined (or the last confirmed value), so callers must check the state before treating it as an answer
 *  (see `known()` in lib/state). */
export function useSetting<T>(key: string, fallback: T) {
  return useQuery({
    queryKey: ["setting", key],
    queryFn: async () => {
      const rows = await must(supabase.from("settings").select("value").eq("key", key));
      return (rows as { value: T }[])[0]?.value ?? fallback;
    },
  });
}

/** The studio timezone for showing dates. A saved name the browser doesn't recognise would break every date on the
 *  page, so such a value shows times in UTC instead, and `useTimezoneProblem` says so in a banner. */
export function useTimezone(): string {
  const saved = useSetting<string>("timezone", "Africa/Nairobi").data ?? "Africa/Nairobi";
  return isValidZone(saved) ? saved : "UTC";
}

/** The saved timezone when it isn't one the browser recognises, otherwise null. */
export function useTimezoneProblem(): string | null {
  const q = useSetting<string>("timezone", "Africa/Nairobi");
  return q.isSuccess && !isValidZone(q.data) ? String(q.data) : null;
}

export function useSaveSetting() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({ key, value, patch }: { key: string; value: unknown; patch?: boolean }) => {
      if (patch) {
        const saved = await patchSetting(key, value as Record<string, unknown>);
        qc.setQueryData(["setting", key], saved);
        return;
      }
      await must(supabase.from("settings").upsert({ key, value }));
      await supabase.from("audit_logs").insert({ actor: "owner", action: "setting_changed", target_type: "setting", target_id: key, details: { value } });
    },
    onSuccess: (_d, v) => { qc.invalidateQueries({ queryKey: ["setting", v.key] }); announceChange([["setting", v.key]]); },
  });
}

export function useAccounts() {
  return useQuery({
    queryKey: ["accounts"],
    queryFn: async () =>
      (await must(
        supabase
          .from("social_accounts")
          .select("id, platform, label, handle, enabled, topic_mix, weekly_targets, oauth_connections(status, last_error, token_expires_at, app_publish_mode)")
          .order("platform"),
      )) as unknown as Account[],
  });
}

/** Ask the engine to do something. The Worker starts the GitHub job right away (or the 15-minute cron picks it up). */
export async function queueJob(jobType: string, opts: { projectId?: string; input?: Record<string, unknown> } = {}): Promise<{ startsSoon: boolean }> {
  const queued = await supabase.rpc("enqueue_owner_job", {
    p_job_type: jobType, p_project_id: opts.projectId ?? null, p_input: opts.input ?? {},
  });
  if (queued.error) {
    if (!missingFunction(queued.error)) throw new Error(friendlyError(queued.error.message));
    // Old schema: preserve existing functionality during the database rollout.
    let activeQuery = supabase.from("generation_jobs").select("id").eq("job_type", jobType)
      .in("status", ["queued", "running", "retrying"]).eq("input", JSON.stringify(opts.input ?? {}));
    activeQuery = opts.projectId ? activeQuery.eq("project_id",opts.projectId) : activeQuery.is("project_id",null);
    const active = await must(activeQuery.limit(1));
    if (!(active as unknown[]).length) await must(supabase.from("generation_jobs").insert({ job_type: jobType,
      project_id: opts.projectId ?? null, input: opts.input ?? {}, requested_by: "owner", status: "queued",
      idempotency_key: `owner:${jobType}:${opts.projectId ?? "all"}:${crypto.randomUUID()}` }));
  }
  announceChange();
  try {
    await callWorker("/api/dispatch", { workflow: "queue" });
    return { startsSoon: true };
  } catch {
    // Worker not reachable: the job is saved and runs on the next scheduled pass (the 15-minute check).
    return { startsSoon: false };
  }
}

export async function runWorkflow(workflow: "research" | "produce" | "publish" | "queue"): Promise<void> {
  await callWorker("/api/dispatch", { workflow });
}

export type StopResult = { stopped: boolean; reason?: string; runs_cancelled: number; jobs_stopped?: number;
  packages?: number; ideas?: number; sources?: number; notifications?: number; files_removed: number };

/** Stop & clear: stops everything that is making content and erases what it made (never anything published). */
export async function stopAndClear(): Promise<StopResult> {
  return callWorker<StopResult>("/api/stop-clear", {});
}

/** Approve exactly the script version the owner reviewed. A changed version is refused, never approved unseen. */
export async function approveProject(projectId: string, reviewedVersion: string | null, notes: string | null = null): Promise<number> {
  if (!reviewedVersion) throw new Error("This package has no script to approve yet. Reload the package.");
  const res = await supabase.rpc("approve_project", { p_project_id: projectId, p_notes: notes, p_expected_version: reviewedVersion });
  if (!res.error) return res.data as number;
  if (!missingFunction(res.error)) throw new Error(friendlyError(res.error.message));
  // Database without migration 14: check the version here first, then use the older approval function.
  const now = (await must(supabase.from("content_projects").select("status, current_script_version_id").eq("id", projectId))) as { status: string; current_script_version_id: string | null }[];
  if (!now[0]) throw new Error("This package no longer exists.");
  if (!["ready_for_review", "needs_attention"].includes(now[0].status)) throw new Error(`This package is no longer waiting for approval (it is ${now[0].status}). Reload to see its current state.`);
  if (now[0].current_script_version_id !== reviewedVersion) throw new Error("The script changed after you opened it. Reload and review the current version before approving.");
  return (await must(supabase.rpc("approve_project", { p_project_id: projectId, p_notes: notes }))) as number;
}

/** Compatible rolling deployment: only fall back when PostgREST confirms the new function is absent. */
export function missingFunction(error: { code?: string; message?: string } | null): boolean {
  return error?.code === "PGRST202" || error?.code === "42883";
}
export async function patchSetting(key: string, patch: Record<string, unknown>, expected?: Record<string, unknown>) {
  const res = await supabase.rpc("patch_studio_setting", { p_key: key, p_patch: patch, p_expected: expected ?? null });
  if (!res.error) return res.data;
  if (!missingFunction(res.error)) throw new Error(friendlyError(res.error.message));
  for (let attempt = 0; attempt < 4; attempt++) {
    const row = await must(supabase.from("settings").select("value").eq("key", key).maybeSingle()) as {value: Record<string, unknown>} | null;
    const current = row?.value ?? {};
    if (expected && Object.entries(expected).some(([k,v]) => current[k] !== v)) throw new Error("This setting changed elsewhere. Reload before trying again.");
    const next = { ...current, ...patch };
    if (row) {
      const updated = await must(supabase.from("settings").update({ value: next }).eq("key", key).eq("value", JSON.stringify(current)).select("key"));
      if ((updated as unknown[]).length) return next;
    } else {
      const insert = await supabase.from("settings").insert({ key, value: next });
      if (!insert.error) return next;
      if (insert.error.code !== "23505") throw new Error(friendlyError(insert.error.message));
    }
  }
  throw new Error("This setting keeps changing in another tab. Try again after those changes finish.");
}
