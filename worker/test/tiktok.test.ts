import { describe, expect, it } from "vitest";
import { choiceProblem, type Creator } from "../src/tiktok";

const creator: Creator = { privacy_level_options: ["PUBLIC_TO_EVERYONE", "SELF_ONLY"], comment_disabled: false,
  duet_disabled: true, stitch_disabled: false, max_video_post_duration_sec: 600, can_post: true };
const ok = { privacy_level: "PUBLIC_TO_EVERYONE", consent: true };

describe("TikTok posting choices (Content Sharing Guidelines)", () => {
  it("needs an audience chosen by the owner, from the account's own options", () => {
    expect(choiceProblem({ consent: true }, creator)).toMatch(/who can watch/);
    expect(choiceProblem({ privacy_level: "FOLLOWER_OF_CREATOR", consent: true }, creator)).toMatch(/isn't available/);
    expect(choiceProblem(ok, creator)).toBeNull();
  });
  it("needs the music consent", () => {
    expect(choiceProblem({ privacy_level: "SELF_ONLY" }, creator)).toMatch(/Music Usage/);
  });
  it("keeps switches the creator turned off, off", () => {
    expect(choiceProblem({ ...ok, allow_duet: true }, creator)).toMatch(/turned off/);
    expect(choiceProblem({ ...ok, allow_comment: true, allow_stitch: true }, creator)).toBeNull();
  });
  it("commercial content must say what it is, and branded content can't be private", () => {
    expect(choiceProblem({ ...ok, disclose: true }, creator)).toMatch(/Your brand/);
    expect(choiceProblem({ privacy_level: "SELF_ONLY", consent: true, disclose: true, branded_content: true }, creator)).toMatch(/can't be private/);
    expect(choiceProblem({ ...ok, disclose: true, your_brand: true }, creator)).toBeNull();
  });
  it("respects the account's longest video and posting limit", () => {
    expect(choiceProblem(ok, creator, 700)).toMatch(/at most 600/);
    expect(choiceProblem(ok, { ...creator, can_post: false })).toMatch(/can't post/);
  });
});

import { afterEach, vi } from "vitest";
import { confirmPost, contentSnapshot, creatorInfo } from "../src/tiktok";
import { Supabase, type Env } from "../src/supabase";
import { handleFetch } from "../src/index";
const env = { SUPABASE_URL: "https://db.test", SUPABASE_SERVICE_ROLE_KEY: "service", SUPABASE_ANON_KEY: "anon",
  TOKEN_ENCRYPTION_KEY: "MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY=" } as Env;
afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });
describe("TikTok saved-content confirmation", () => {
  it("requires a saved content snapshot and loaded video duration", async () => {
    vi.spyOn(Supabase.prototype, "select").mockResolvedValue([{ id: "p", status: "scheduled", social_accounts: { platform: "tiktok" } }] as any);
    const rpc = vi.spyOn(Supabase.prototype, "rpc");
    await expect(confirmPost(env, "owner", { post_id: "p", choices: ok, seconds: 30 })).rejects.toThrow("Reopen TikTok settings");
    await expect(confirmPost(env, "owner", { post_id: "p", choices: ok, content_snapshot: {} as any })).rejects.toThrow("preview to load");
    expect(rpc).not.toHaveBeenCalled();
  });
  it("does not change an upload that is still processing", async () => {
    vi.spyOn(Supabase.prototype, "select").mockResolvedValue([{ id: "p", status: "processing", social_accounts: { platform: "tiktok" } }] as any);
    const rpc = vi.spyOn(Supabase.prototype, "rpc");
    await expect(confirmPost(env, "owner", { post_id: "p", clear: true })).rejects.toThrow("being published");
    expect(rpc).not.toHaveBeenCalled();
  });
  it("the displayed content comes from the server's snapshot function", async () => {
    const snapshot = { account_id: "account", body: "Saved caption", preview_key: "clip.mp4" };
    const rpc = vi.spyOn(Supabase.prototype, "rpc").mockResolvedValue(snapshot);
    expect(await contentSnapshot(env, "p")).toEqual(snapshot);
    expect(rpc).toHaveBeenCalledWith("tiktok_content_snapshot", { p_post_id: "p" });
  });
  it("an upload-only connection does not call the unauthorized Direct Post creator endpoint", async () => {
    vi.spyOn(Supabase.prototype, "select").mockImplementation(async table => (table === "social_accounts" ? [{ id: "account" }] : [{ scopes: ["video.upload"] }]) as any);
    expect((await creatorInfo(env, "account")).direct_post).toBe(false);
  });
  it.each(["content", "creator", "confirm"])("protects the %s endpoint from unauthenticated callers", async path => {
    const fetch = vi.fn(async (_url: unknown) => new Response("[]", { status: 200 }));
    vi.stubGlobal("fetch", fetch);
    const res = await handleFetch(new Request(`https://worker.test/api/tiktok/${path}`, { method: "POST", body: "{}" }), env);
    expect(res.status).toBe(401);
    expect(fetch.mock.calls.some(([url]) => String(url).includes("open.tiktokapis.com"))).toBe(false);
  });
});
