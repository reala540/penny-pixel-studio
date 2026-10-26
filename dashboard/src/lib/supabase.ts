import { createClient } from "@supabase/supabase-js";
import { friendlyError } from "./state";

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
  let res: Response;
  try {
    res = await fetch(`${workerUrl}${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${data.session?.access_token ?? ""}` },
      body: JSON.stringify(body),
    });
  } catch (e) {  // offline, or the Worker can't be reached: nothing was done
    throw new Error(friendlyError(e));
  }
  const json = (await res.json().catch(() => ({}))) as T & { error?: string };
  if (res.status === 401) throw new Error(data.session ? "Your sign-in has expired. Sign in again: you'll come back to this page." : "Sign in first.");
  if (!res.ok) throw new Error(friendlyError(json.error || `The studio's server answered ${res.status}. Check the current state before retrying.`));
  return json;
}

export async function signedUrl(key: string | null | undefined, seconds = 3600): Promise<string | null> {
  if (!key) return null;
  const { data, error } = await supabase.storage.from("studio").createSignedUrl(key, seconds);
  if (error) throw new Error(friendlyError(error.message));
  return data?.signedUrl ?? null;
}

let deliberate = false;
/** Sign out on purpose (so the sign-in page doesn't say the session expired). */
export async function signOut(): Promise<void> {
  deliberate = true;
  await supabase.auth.signOut();
}
export const signedOutDeliberately = () => deliberate;
