// Unfinished "Create content" work, kept on this device so leaving the page (or closing the tab) never loses it.
// Drafts belong to the signed-in owner, hold only choices and the owner's own idea text (never keys or tokens),
// and are reconciled with the database before they're offered: the database always wins.
import { createContext, useCallback, useContext, useEffect, useState, useSyncExternalStore } from "react";
import { announceChange } from "./state";

export type DraftStep = "channel" | "idea" | "research" | "package" | "progress";
export interface CreateDraft {
  id: string;
  /** Bumped on every save: a save based on an older rev is a conflict (another tab changed it). */
  rev: number;
  updatedAt: string;
  step: DraftStep;
  channel: "ai" | "money" | "both" | null;
  kind: "generated" | "research" | null;
  ideaId: string | null;
  ideaTitle?: string | null;
  /** "Write my own idea" text and its options. */
  own?: string;
  depth?: number;
}

export const MAX_DRAFTS = 100;
export const DRAFT_DAYS = 30;
const PREFIX = "studio-create-drafts:";

// ------------------------------------------------------------------ owner

/** The signed-in owner's user id (set by AuthGate). Drafts are never shared between accounts. */
export const OwnerContext = createContext<string | null>(null);
export const useOwnerId = () => useContext(OwnerContext);

// ------------------------------------------------------------------ safety

/** True when text looks like a key, token or password: such text is never written to the device. */
export function looksLikeSecret(text: string): boolean {
  return /\b(sk|pk|rk|gsk|xai|hf|ghp|gho|github_pat|AIza|ya29|eyJ)[-_A-Za-z0-9]{12,}/.test(text)
    || /\b[A-Za-z0-9_\-]{40,}\b/.test(text)
    || /(api[_ -]?key|password|secret|token)\s*[:=]\s*\S{6,}/i.test(text);
}

/** What may be stored: known fields only, bounded, without secret-looking text. */
export function cleanDraft(d: CreateDraft): CreateDraft {
  const own = (d.own ?? "").slice(0, 2000);
  return {
    id: String(d.id).slice(0, 64), rev: Number(d.rev) || 0, updatedAt: d.updatedAt, step: d.step,
    channel: d.channel ?? null, kind: d.kind ?? null, ideaId: d.ideaId ?? null,
    ideaTitle: d.ideaTitle ? String(d.ideaTitle).slice(0, 200) : null,
    own: own && !looksLikeSecret(own) ? own : "",
    depth: [2, 3, 5].includes(Number(d.depth)) ? Number(d.depth) : 3,
  };
}

/** A draft with nothing chosen and nothing typed isn't worth offering. */
export function isEmptyDraft(d: CreateDraft): boolean {
  return !d.channel && !d.ideaId && !(d.own ?? "").trim();
}

// ------------------------------------------------------------------ storage

function read(owner: string): CreateDraft[] {
  try {
    const raw = JSON.parse(localStorage.getItem(PREFIX + owner) ?? "[]");
    if (!Array.isArray(raw)) return [];
    const cutoff = Date.now() - DRAFT_DAYS * 86_400_000;
    return raw.filter((d) => d && typeof d.id === "string" && Date.parse(d.updatedAt) > cutoff).map(cleanDraft)
      .sort((a, b) => b.updatedAt.localeCompare(a.updatedAt));
  } catch {
    return [];
  }
}

function write(owner: string, drafts: CreateDraft[]): boolean {
  try {
    const keep = drafts.filter((d) => !isEmptyDraft(d)).sort((a, b) => b.updatedAt.localeCompare(a.updatedAt)).slice(0, MAX_DRAFTS);
    localStorage.setItem(PREFIX + owner, JSON.stringify(keep.map(cleanDraft)));
    notify();
    announceChange([["drafts"]]);
    return true;
  } catch {
    return false;  // private mode or storage full: the page still works, the draft just isn't kept
  }
}

export function listDrafts(owner: string | null): CreateDraft[] {
  return owner ? read(owner) : [];
}

export function getDraft(owner: string | null, id: string | null): CreateDraft | null {
  return owner && id ? read(owner).find((d) => d.id === id) ?? null : null;
}

export type SaveResult = { ok: true; draft: CreateDraft } | { ok: false; reason: "conflict"; newer: CreateDraft } | { ok: false; reason: "storage" };

/** Save a draft. `baseRev` is the rev this change was made from; if the stored draft moved on, it's a conflict. */
export function saveDraft(owner: string, draft: Omit<CreateDraft, "rev" | "updatedAt">, baseRev: number | null, force = false): SaveResult {
  const all = read(owner);
  const stored = all.find((d) => d.id === draft.id);
  if (stored && !force && baseRev !== null && stored.rev !== baseRev) return { ok: false, reason: "conflict", newer: stored };
  const next = cleanDraft({ ...draft, rev: (stored?.rev ?? 0) + 1, updatedAt: new Date().toISOString() });
  return write(owner, [next, ...all.filter((d) => d.id !== draft.id)]) ? { ok: true, draft: next } : { ok: false, reason: "storage" };
}

export function removeDraft(owner: string | null, id: string): void {
  if (!owner) return;
  try {
    const key=`studio-draft-removed:${owner}`;
    const removed: string[]=JSON.parse(localStorage.getItem(key)??"[]");
    localStorage.setItem(key,JSON.stringify([...new Set([...removed,id])]));
  } catch { /* device copy still removed */ }
  write(owner, read(owner).filter((d) => d.id !== id));
}

export function newDraftId(): string {
  return typeof crypto !== "undefined" && "randomUUID" in crypto ? crypto.randomUUID() : `d${Date.now()}${Math.random().toString(16).slice(2)}`;
}

// ------------------------------------------------------------------ live list (this tab and others)

const listeners = new Set<() => void>();
let version = 0;
function notify() { version++; listeners.forEach((l) => l()); }
function subscribe(cb: () => void) {
  listeners.add(cb);
  const onStorage = (e: StorageEvent) => { if (!e.key || e.key.startsWith(PREFIX)) notify(); };
  window.addEventListener("storage", onStorage);  // another tab saved
  return () => { listeners.delete(cb); window.removeEventListener("storage", onStorage); };
}

/** The owner's drafts, newest first, updating when this or another tab changes them. */
export function useDrafts(): CreateDraft[] {
  const owner = useOwnerId();
  const v = useSyncExternalStore(subscribe, () => version, () => 0);
  const [list, setList] = useState<CreateDraft[]>(() => listDrafts(owner));
  useEffect(() => setList(listDrafts(owner)), [owner, v]);
  return list;
}

/** Re-read drafts when something outside this module changed storage (e.g. a test or another tab). */
export function useRefreshDrafts(): () => void {
  return useCallback(() => notify(), []);
}

/** Merge downloaded bookmarks without dropping a newer local edit. */
export function mergeCloudDrafts(owner: string, drafts: CreateDraft[]): void {
  const current = read(owner);
  const next = [...drafts].sort((a,b)=>b.updatedAt.localeCompare(a.updatedAt));
  if(JSON.stringify(current)!==JSON.stringify(next)) write(owner,next);
}
