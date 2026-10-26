// Stop & clear: the one button under "Running now". Stops everything that is making content and erases what
// that work made, from the ideas it started from up to now. Published posts are never touched.

import { Env, Supabase } from "./supabase";

// Only the workflows that make content. Publishing is left alone: stopping an upload half-way is exactly the
// unclear case the strict duplicate rules hold for a person, so it finishes on its own.
const STOPPABLE = ["queue.yml", "weekly-research.yml", "weekly-produce.yml"];

type Run = { id: number; path?: string; status: string };

function gh(env: Env, path: string, method = "GET"): Promise<Response> {
  return fetch(`https://api.github.com/repos/${env.GITHUB_REPO}${path}`, {
    method,
    headers: {
      Authorization: `Bearer ${env.GITHUB_TOKEN}`,
      Accept: "application/vnd.github+json",
      "User-Agent": "penny-pixel-studio",
      "X-GitHub-Api-Version": "2022-11-28",
    },
  });
}

/** Cancels the running and waiting content runs on GitHub. Returns how many were cancelled. */
export async function cancelRuns(env: Env): Promise<number> {
  if (!env.GITHUB_REPO || !env.GITHUB_TOKEN) return 0;
  let n = 0;
  for (const status of ["in_progress", "queued", "waiting", "pending"]) {
    const r = await gh(env, `/actions/runs?status=${status}&per_page=50`);
    if (!r.ok) continue;
    const runs = ((await r.json()) as { workflow_runs?: Run[] }).workflow_runs ?? [];
    for (const run of runs) {
      if (!STOPPABLE.some((f) => run.path?.endsWith(f))) continue;
      const c = await gh(env, `/actions/runs/${run.id}/cancel`, "POST");
      if (c.status === 202) n += 1; // accepted requests only; 409 means it already finished
    }
  }
  return n;
}

/** Removes stored files (videos, audio, images) in batches. Best effort: a leftover file is harmless. */
export async function removeFiles(env: Env, paths: string[]): Promise<number> {
  let removed = 0;
  for (let i = 0; i < paths.length; i += 100) {
    const batch = paths.slice(i, i + 100);
    const r = await fetch(`${env.SUPABASE_URL}/storage/v1/object/studio`, {
      method: "DELETE",
      headers: {
        apikey: env.SUPABASE_SERVICE_ROLE_KEY,
        Authorization: `Bearer ${env.SUPABASE_SERVICE_ROLE_KEY}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ prefixes: batch }),
    });
    if (r.ok) removed += batch.length;
  }
  return removed;
}

export type StopResult = {
  stopped: boolean;
  reason?: string;
  runs_cancelled: number;
  jobs_stopped?: number;
  packages?: number;
  ideas?: number;
  sources?: number;
  notifications?: number;
  files_removed: number;
};

export async function stopAndClear(env: Env): Promise<StopResult> {
  const db = new Supabase(env);
  // GitHub first, so nothing keeps writing; the database then tells any run still shutting down to stop
  const runs = await cancelRuns(env);
  const out = await db.rpc<{ stopped: boolean; reason?: string; storage_paths?: string[] } & Record<string, unknown>>(
    "stop_and_clear", {});
  const files = out.stopped ? await removeFiles(env, out.storage_paths ?? []) : 0;
  await db.audit("stop_and_clear_button", { runs_cancelled: runs, files_removed: files, stopped: out.stopped }, "owner");
  const { storage_paths: _paths, ...rest } = out;
  return { ...(rest as Omit<StopResult, "runs_cancelled" | "files_removed">), runs_cancelled: runs, files_removed: files };
}
