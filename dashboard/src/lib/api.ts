import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { announceChange, friendlyError } from "./state";
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

export function useTimezone(): string {
  return useSetting<string>("timezone", "Africa/Nairobi").data ?? "Africa/Nairobi";
}

export function useSaveSetting() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({ key, value }: { key: string; value: unknown }) => {
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
  await must(
    supabase.from("generation_jobs").insert({
      job_type: jobType,
      project_id: opts.projectId ?? null,
      idempotency_key: `owner:${jobType}:${opts.projectId ?? "all"}:${crypto.randomUUID()}`,
      status: "queued",
      requested_by: "owner",
      input: opts.input ?? {},
    }),
  );
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
