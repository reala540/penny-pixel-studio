import { beforeEach, describe, expect, it } from "vitest";
import { draftLabel, draftState, draftUrl, type DraftFacts } from "./draftStatus";
import { cleanDraft, getDraft, isEmptyDraft, listDrafts, looksLikeSecret, MAX_DRAFTS, removeDraft, saveDraft, type CreateDraft } from "./drafts";

// a tiny in-memory localStorage for node
const store = new Map<string, string>();
Object.assign(globalThis, {
  localStorage: { getItem: (k: string) => store.get(k) ?? null, setItem: (k: string, v: string) => void store.set(k, v), removeItem: (k: string) => void store.delete(k) },
  window: { addEventListener() {}, removeEventListener() {} },
});

const base = (over: Partial<CreateDraft> = {}) => ({ id: "d1", step: "idea" as const, channel: "ai" as const, kind: null, ideaId: null, ...over });

describe("drafts", () => {
  beforeEach(() => store.clear());

  it("are kept per owner: another account never sees them", () => {
    saveDraft("owner-a", base(), null);
    expect(listDrafts("owner-a")).toHaveLength(1);
    expect(listDrafts("owner-b")).toEqual([]);
    expect(listDrafts(null)).toEqual([]);
  });

  it("keep several drafts, newest first, and at most MAX_DRAFTS", () => {
    for (let i = 0; i < MAX_DRAFTS + 3; i++) saveDraft("o", base({ id: `d${i}` }), null);
    const all = listDrafts("o");
    expect(all).toHaveLength(MAX_DRAFTS);
    expect(all[0].id).toBe(`d${MAX_DRAFTS + 2}`);
  });

  it("a save from an older version is a conflict, unless forced", () => {
    const first = saveDraft("o", base(), null);
    if (!first.ok) throw new Error("save failed");
    const tabA = saveDraft("o", base({ step: "research" }), first.draft.rev);
    expect(tabA.ok).toBe(true);
    const tabB = saveDraft("o", base({ step: "package" }), first.draft.rev);  // still based on rev 1
    expect(tabB).toMatchObject({ ok: false, reason: "conflict" });
    expect(getDraft("o", "d1")?.step).toBe("research");
    expect(saveDraft("o", base({ step: "package" }), first.draft.rev, true).ok).toBe(true);
    expect(getDraft("o", "d1")?.step).toBe("package");
  });

  it("never store secret-looking text", () => {
    expect(looksLikeSecret("my key is sk-abcdefghijklmnopqrstuvwx")).toBe(true);
    expect(looksLikeSecret("api_key = 12345678")).toBe(true);
    expect(looksLikeSecret("Three AI tools that save small shops time")).toBe(false);
    saveDraft("o", base({ own: "use gsk_abcdefghijklmnopqrstuvwxyz123" }), null);
    expect(getDraft("o", "d1")?.own).toBe("");
  });

  it("store only known fields", () => {
    const d = cleanDraft({ ...base(), rev: 1, updatedAt: new Date().toISOString(), password: "x" } as unknown as CreateDraft);
    expect(Object.keys(d)).not.toContain("password");
  });

  it("empty drafts aren't kept; removing works", () => {
    saveDraft("o", base({ channel: null }), null);
    expect(listDrafts("o")).toEqual([]);
    expect(isEmptyDraft({ ...base(), channel: null, rev: 0, updatedAt: "" })).toBe(true);
    saveDraft("o", base(), null);
    removeDraft("o", "d1");
    expect(listDrafts("o")).toEqual([]);
  });

  it("drop drafts older than 30 days and survive broken storage", () => {
    store.set("studio-create-drafts:o", JSON.stringify([{ ...base(), rev: 1, updatedAt: "2020-01-01T00:00:00Z" }]));
    expect(listDrafts("o")).toEqual([]);
    store.set("studio-create-drafts:o", "{not json");
    expect(listDrafts("o")).toEqual([]);
  });
});

describe("draft state comes from the database", () => {
  const d = { id: "d1", rev: 1, updatedAt: new Date().toISOString(), step: "package" as const, channel: "ai" as const, kind: "generated" as const, ideaId: "g1", ideaTitle: "Prompts" };
  const facts = (over: Partial<DraftFacts> = {}): DraftFacts => ({ ideas: { g1: { title: "Prompts", contentIdeaId: "c1" } }, projects: {}, jobs: {}, ...over });

  it("not started: continue at the saved step", () => {
    expect(draftState(d, facts())).toEqual({ state: "draft" });
    expect(draftUrl(d)).toBe("/create?draft=d1&step=package&channel=ai&kind=generated&id=g1");
  });
  it("deleted idea: back to choosing an idea, channel kept", () => {
    const s = draftState(d, facts({ ideas: {} }));
    expect(s.state).toBe("missing");
    expect(draftUrl(d, s)).toBe("/create?draft=d1&step=idea&channel=ai");
    expect(draftLabel(d, s)).toContain("no longer exists");
  });
  it("being made or failed: open progress (where Try again lives), never start anything", () => {
    expect(draftUrl(d, draftState(d, facts({ jobs: { g1: { status: "running", error_message: null, project_id: null } } })))).toContain("step=progress");
    const f = draftState(d, facts({ jobs: { g1: { status: "failed", error_message: "boom", project_id: "p1" } } }));
    expect(f).toMatchObject({ state: "failed", error: "boom", projectId: "p1" });
  });
  it("made: points at the package itself", () => {
    const s = draftState(d, facts({ projects: { c1: { id: "p1", status: "ready_for_review" } } }));
    expect(draftUrl(d, s)).toBe("/content/p1");
  });
  it("couldn't check: says so", () => {
    expect(draftState(d, undefined)).toEqual({ state: "unknown" });
    expect(draftLabel(d, { state: "unknown" })).toContain("couldn't check");
  });
  it("a draft with no idea yet names its channel", () => {
    expect(draftLabel({ ...d, ideaId: null, ideaTitle: null, channel: "money", step: "idea" }, { state: "draft" })).toBe("A new Penny · Money package: choosing an idea.");
  });
});
