import { describe, expect, it } from "vitest";
import { stageRows } from "./content";
import { readiness } from "./readiness";

const now = Date.parse("2026-10-25T12:00:00Z");
const models = [
  { provider: "groq", roles: ["scriptwriter", "voice_editor", "critic", "claim_checker", "repurposer"], enabled: true },
  { provider: "nvidia", roles: ["research_summarizer"], enabled: true },
];
const providers = [{ name: "groq", enabled: true }, { name: "nvidia", enabled: true }];
const core = { core: { database: { ok: true, detail: "" }, github: { ok: true, detail: "" } } };

describe("can the studio create?", () => {
  it("needs only the Worker, the database and a working AI service, not Telegram or accounts", () => {
    const r = readiness({ worker: true, core, check: { checked_at: "2026-10-25T10:00:00Z", results: [{ provider: "groq", status: "ok" }, { provider: "nvidia", status: "ok" }] }, models, providers, now });
    expect(r.canCreate).toBe(true);
    expect(r.blockers).toEqual([]);
    expect(r.warnings).toEqual([]);
  });

  it("blocks without the Worker, a reachable database, or any passing AI service", () => {
    expect(readiness({ worker: false, core, check: null, now }).canCreate).toBe(false);
    expect(readiness({ worker: true, core: { core: { database: { ok: false, detail: "" } } }, check: { checked_at: "2026-10-25T10:00:00Z", results: [{ provider: "groq", status: "ok" }] }, now }).canCreate).toBe(false);
    const none = readiness({ worker: true, core, check: { checked_at: "2026-10-25T10:00:00Z", results: [{ provider: "groq", status: "failed" }] }, now });
    expect(none.canCreate).toBe(false);
    expect(none.blockers[0].text).toContain("No AI service passed");
  });

  it("treats an old check as possibly stale, without blocking", () => {
    const r = readiness({ worker: true, core, check: { checked_at: "2026-10-23T10:00:00Z", results: [{ provider: "groq", status: "ok" }, { provider: "nvidia", status: "ok" }] }, models, providers, now });
    expect(r.canCreate).toBe(true);
    expect(r.stale).toBe(true);
    expect(r.warnings.some((w) => w.text.includes("50 hours old"))).toBe(true);
  });

  it("never claims every job is covered just because one service passed", () => {
    const r = readiness({ worker: true, core, check: { checked_at: "2026-10-25T10:00:00Z", results: [{ provider: "groq", status: "ok" }, { provider: "nvidia", status: "failed" }] }, models, providers, now });
    expect(r.canCreate).toBe(true);
    expect(r.uncoveredRoles).toEqual(["Evidence scout"]);
    expect(r.warnings.some((w) => w.text.includes("Evidence scout"))).toBe(true);
  });
});

describe("progress shows only real stages", () => {
  const j = (job_type: string, status: string, error_message: string | null = null) => ({ id: job_type + status + Math.random(), job_type, status, error_message, project_id: "p", updated_at: "" });
  it("maps stage jobs and counts previews, without inventing steps", () => {
    const rows = stageRows([j("script", "completed"), j("package", "completed"), j("render_preview", "completed"), j("render_preview", "running"), j("render_preview", "pending")]);
    expect(rows.map((r) => [r.key, r.state, r.detail])).toEqual([
      ["script", "done", undefined], ["package", "done", undefined], ["render_preview", "running", "1 of 3 done"], ["thumbnails", "waiting", undefined],
    ]);
  });
  it("shows the stored error for a step that didn't work", () => {
    const rows = stageRows([j("script", "retrying", "All providers failed for 'research_summarizer'")]);
    expect(rows[0]).toMatchObject({ state: "failed", error: "All providers failed for 'research_summarizer'" });
    expect(rows.slice(1).every((r) => r.state === "waiting")).toBe(true);
  });
});

describe("readiness never reads a failed load as an answer", () => {
  it("a failed key-check load is not 'never checked' and not 'no service passed'", () => {
    const r = readiness({ worker: true, check: null, checkError: true });
    expect(r.warnings.map((w) => w.text)).toEqual(["Couldn't load the last AI key check."]);
    expect(r.blockers).toEqual([]);
    expect(r.checkError).toBe(true);
  });
  it("a failed model list doesn't claim every job is uncovered", () => {
    const r = readiness({ worker: true, check: { checked_at: new Date().toISOString(), results: [{ provider: "groq", status: "ok" }] }, aiError: true });
    expect(r.uncoveredRoles).toEqual([]);
    expect(r.warnings.map((w) => w.text)).toEqual(["Couldn't load the AI services and models."]);
  });
});
