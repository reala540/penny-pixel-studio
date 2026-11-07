// Disconnecting an account: Google is asked to revoke YouTube access, the saved login is deleted and the account
// shows as disconnected. Only the owner can do it. All network calls are mocked.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { encryptJson } from "../src/crypto";
import { handleFetch } from "../src/index";
import { clearSecretCache } from "../src/setup";
import type { Env } from "../src/supabase";

const KEY = "MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY=";
const env = (): Env => ({ SUPABASE_URL: "https://db.test", SUPABASE_SERVICE_ROLE_KEY: "service", SUPABASE_ANON_KEY: "anon",
  TOKEN_ENCRYPTION_KEY: KEY, DASHBOARD_URL: "https://dash.test", GITHUB_REPO: "me/studio", GITHUB_REF: "main", GITHUB_TOKEN: "gh" } as Env);
const ok = (data: unknown, status = 200) => new Response(JSON.stringify(data), { status });
type Route = (url: string, init?: RequestInit) => Response | undefined;
let routes: Route[] = [];
const calls: { url: string; init?: RequestInit }[] = [];

beforeEach(() => {
  routes = [];
  calls.length = 0;
  clearSecretCache();
  vi.stubGlobal("fetch", async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    calls.push({ url, init });
    for (const r of routes) { const res = r(url, init); if (res) return res; }
    return new Response("[]", { status: 200 });
  });
});
afterEach(() => vi.unstubAllGlobals());

const owner = () => {
  routes.push((u) => (u.includes("/auth/v1/user") ? ok({ id: "owner" }) : undefined));
  routes.push((u) => (u.includes("/rest/v1/app_owner") ? ok([{ user_id: "owner" }]) : undefined));
};
async function account(platform: string) {
  const ciphertext = await encryptJson(KEY, { access_token: "at", refresh_token: "rt" });
  routes.push((u, i) => (u.includes("/rest/v1/social_accounts") && (!i?.method || i.method === "GET") ? ok([{ id: "acc1", platform, handle: "@me" }]) : undefined));
  routes.push((u, i) => (u.includes("/rest/v1/oauth_secrets") && (!i?.method || i.method === "GET") ? ok([{ ciphertext }]) : undefined));
}
const disconnect = (auth = "Bearer session") => handleFetch(new Request("https://w.test/api/oauth/disconnect", {
  method: "POST", headers: { Authorization: auth, "Content-Type": "application/json" }, body: JSON.stringify({ account_id: "acc1" }) }), env());

describe("Disconnect", () => {
  it("revokes Google access, deletes the saved login and marks the account disconnected", async () => {
    owner();
    await account("youtube");
    routes.push((u) => (u.includes("oauth2.googleapis.com/revoke") ? new Response("", { status: 200 }) : undefined));
    const res = await disconnect();
    expect(await res.json()).toEqual({ platform: "youtube", revoked: true });
    const revoke = calls.find((c) => c.url.includes("oauth2.googleapis.com/revoke"))!;
    expect(String(revoke.init!.body)).toBe("token=rt");
    expect(calls.some((c) => c.url.includes("/rest/v1/oauth_secrets?social_account_id=eq.acc1") && c.init?.method === "DELETE")).toBe(true);
    const patch = calls.find((c) => c.url.includes("/rest/v1/oauth_connections") && c.init?.method === "PATCH")!;
    expect(JSON.parse(String(patch.init!.body))).toMatchObject({ status: "disconnected", scopes: [] });
  });

  it("still deletes the saved login when Google can't be reached", async () => {
    owner();
    await account("youtube");
    routes.push((u) => (u.includes("oauth2.googleapis.com/revoke") ? new Response("", { status: 503 }) : undefined));
    expect(await (await disconnect()).json()).toEqual({ platform: "youtube", revoked: false });
    expect(calls.some((c) => c.url.includes("/rest/v1/oauth_secrets") && c.init?.method === "DELETE")).toBe(true);
  });

  it("other platforms: the saved login is deleted, nothing is sent to Google", async () => {
    owner();
    await account("facebook");
    expect(await (await disconnect()).json()).toEqual({ platform: "facebook", revoked: false });
    expect(calls.some((c) => c.url.includes("googleapis"))).toBe(false);
    expect(calls.some((c) => c.url.includes("/rest/v1/oauth_secrets") && c.init?.method === "DELETE")).toBe(true);
  });

  it("only the owner can disconnect", async () => {
    routes.push((u) => (u.includes("/auth/v1/user") ? ok({}, 401) : undefined));
    expect((await disconnect("Bearer someone")).status).toBe(401);
    expect(calls.some((c) => c.init?.method === "DELETE")).toBe(false);
  });
});
