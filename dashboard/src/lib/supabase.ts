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

/** A stored file that no longer exists (its storage period ended or it was cleared), as opposed to a failed request. */
export class MissingFileError extends Error {
  constructor() { super("This file is no longer stored (its storage period ended or it was cleared)."); this.name = "MissingFileError"; }
}

/** A fresh download link on every call, so an old link never expires on the owner; a deleted file says so. */
export async function signedUrl(key: string | null | undefined, seconds = 3600): Promise<string | null> {
  if (!key) return null;
  const { data, error } = await supabase.storage.from("studio").createSignedUrl(key, seconds);
  if (error) {
    const status = (error as { statusCode?: string | number; status?: number }).statusCode ?? (error as { status?: number }).status;
    if (String(status) === "404" || /not.?found/i.test(error.message)) throw new MissingFileError();
    throw new Error(friendlyError(error.message));
  }
  return data?.signedUrl ?? null;
}

let deliberate = false;
/** Sign out on purpose (so the sign-in page doesn't say the session expired). */
export async function signOut(): Promise<void> {
  deliberate = true;
  await supabase.auth.signOut();
}
export const signedOutDeliberately = () => deliberate;
