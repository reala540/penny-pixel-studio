// What the dashboard knows about a piece of data. A failed or unfinished request is never read as an answer:
// "OFF", "not paused", "no problems" or "not linked" are shown only when the database confirmed them.
import type { UseQueryResult } from "@tanstack/react-query";
import { useEffect, useSyncExternalStore } from "react";

export type Known<T> =
  | { state: "loading" }
  | { state: "offline"; last?: T }
  | { state: "failed"; error: string; last?: T }
  | { state: "not_configured"; what: string }
  | { state: "confirmed"; value: T };

/** The state of a query, keeping the last confirmed value (if any) alongside a failure so it can be shown as "last known". */
export function known<T>(q: Pick<UseQueryResult<T>, "isLoading" | "isError" | "error" | "data" | "isSuccess" | "dataUpdatedAt">,
                         online = typeof navigator === "undefined" || navigator.onLine !== false): Known<T> {
  const last = q.dataUpdatedAt ? q.data : undefined;
  if (q.isError) return online ? { state: "failed", error: friendlyError(q.error), last } : { state: "offline", last };
  if (q.isSuccess) return { state: "confirmed", value: q.data as T };
  if (!online) return { state: "offline", last };
  return { state: "loading" };
}

export function isConfirmed<T>(k: Known<T>): k is { state: "confirmed"; value: T } {
  return k.state === "confirmed";
}

/** Plain-language errors: never a raw stack, never a secret, always what to do next. */
export function friendlyError(error: unknown): string {
  const raw = error instanceof Error ? error.message : typeof error === "string" ? error : "";
  const low = raw.toLowerCase();
  if (!raw) return "Something went wrong. Try again.";
  if (low.includes("failed to fetch") || low.includes("networkerror") || low.includes("load failed") || low.includes("network request failed"))
    return "Couldn't reach the studio. Check your internet connection, then try again.";
  if (low.includes("jwt expired") || low.includes("invalid jwt") || low.includes("session") && low.includes("expired") || low.includes("not authorised") && low.includes("401"))
    return "Your sign-in has expired. Sign in again: you'll come back to this page.";
  if (low.includes("row-level security") || low.includes("permission denied"))
    return "Not allowed: only the studio owner can do this.";
  if (low.includes("duplicate key") || low.includes("already exists"))
    return "That already exists, so nothing new was added.";
  if (low.includes("timeout") || low.includes("timed out"))
    return "The studio took too long to answer. Try again in a moment.";
  return raw.length > 300 ? `${raw.slice(0, 300)}…` : raw;
}

// ------------------------------------------------------------------ connection

function subscribeOnline(cb: () => void) {
  window.addEventListener("online", cb);
  window.addEventListener("offline", cb);
  return () => { window.removeEventListener("online", cb); window.removeEventListener("offline", cb); };
}

/** True while the browser has a network connection (it can still fail to reach the studio). */
export function useOnline(): boolean {
  return useSyncExternalStore(subscribeOnline, () => navigator.onLine, () => true);
}

// ------------------------------------------------------------------ other tabs

const CHANNEL = "penny-pixel-studio";
type SyncMessage = { kind: "changed"; keys?: string[][] };

let channel: BroadcastChannel | null = null;
function getChannel(): BroadcastChannel | null {
  if (channel || typeof BroadcastChannel === "undefined") return channel;
  try { channel = new BroadcastChannel(CHANNEL); } catch { channel = null; }
  return channel;
}

/** Tell the studio's other open tabs that something changed, so they refresh instead of showing old data. */
export function announceChange(keys?: string[][]): void {
  try { getChannel()?.postMessage({ kind: "changed", keys } satisfies SyncMessage); } catch { /* best effort */ }
}

/** Refresh this tab when another tab changed something. */
export function useOtherTabChanges(refresh: (keys?: string[][]) => void): void {
  useEffect(() => {
    const ch = getChannel();
    if (!ch) return;
    const onMessage = (e: MessageEvent<SyncMessage>) => { if (e.data?.kind === "changed") refresh(e.data.keys); };
    ch.addEventListener("message", onMessage);
    return () => ch.removeEventListener("message", onMessage);
  }, [refresh]);
}

// ------------------------------------------------------------------ return after sign-in

const RETURN_KEY = "studio-return-to";

/** Remember where the owner was going, so signing in (or confirming an email) brings them back there. */
export function rememberDestination(path: string): void {
  if (!path || path === "/" || path.startsWith("/demo")) return;
  try { sessionStorage.setItem(RETURN_KEY, path); localStorage.setItem(RETURN_KEY, path); } catch { /* private mode */ }
}

/** The remembered destination (once), if it's a safe in-app path. */
export function takeDestination(): string | null {
  let path: string | null = null;
  try {
    path = sessionStorage.getItem(RETURN_KEY) ?? localStorage.getItem(RETURN_KEY);
    sessionStorage.removeItem(RETURN_KEY);
    localStorage.removeItem(RETURN_KEY);
  } catch { return null; }
  return safePath(path);
}

/** Only same-site paths: never another site (open-redirect safe). */
export function safePath(path: string | null | undefined): string | null {
  if (!path || !path.startsWith("/") || path.startsWith("//") || path.includes("\\")) return null;
  return path;
}
