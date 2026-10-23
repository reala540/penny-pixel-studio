import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { callWorker, supabase } from "./supabase";
import type { Account } from "./types";

export async function must<T>(p: PromiseLike<{ data: T | null; error: { message: string } | null }>): Promise<T> {
  const { data, error } = await p;
  if (error) throw new Error(error.message);
  return data as T;
}

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
    onSuccess: (_d, v) => qc.invalidateQueries({ queryKey: ["setting", v.key] }),
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
export async function queueJob(jobType: string, opts: { projectId?: string; input?: Record<string, unknown> } = {}): Promise<void> {
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
  try {
    await callWorker("/api/dispatch", { workflow: "queue" });
  } catch {
    // Worker not configured yet: the job waits in the queue and runs on the next scheduled pass.
  }
}

export async function runWorkflow(workflow: "research" | "produce" | "publish" | "queue"): Promise<void> {
  await callWorker("/api/dispatch", { workflow });
}
