import { createClient } from "@supabase/supabase-js";

const url = import.meta.env.VITE_SUPABASE_URL as string | undefined;
const anon = import.meta.env.VITE_SUPABASE_ANON_KEY as string | undefined;

export const configured = Boolean(url && anon);

// The anon key is public by design; Row Level Security decides what the signed-in owner can see.
export const supabase = createClient(url || "http://localhost:54321", anon || "public-anon-key", {
  auth: { persistSession: true, autoRefreshToken: true },
});

export const workerUrl = (import.meta.env.VITE_WORKER_URL as string | undefined)?.replace(/\/$/, "") ?? "";

export async function callWorker<T>(path: string, body: unknown): Promise<T> {
  if (!workerUrl) throw new Error("The Worker address (VITE_WORKER_URL) is not set. See GUIDE.md, step 9.");
  const { data } = await supabase.auth.getSession();
  const res = await fetch(`${workerUrl}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${data.session?.access_token ?? ""}` },
    body: JSON.stringify(body),
  });
  const json = (await res.json().catch(() => ({}))) as T & { error?: string };
  if (!res.ok) throw new Error(json.error || `Worker returned ${res.status}`);
  return json;
}

export async function signedUrl(key: string | null | undefined, seconds = 3600): Promise<string | null> {
  if (!key) return null;
  const { data } = await supabase.storage.from("studio").createSignedUrl(key, seconds);
  return data?.signedUrl ?? null;
}
