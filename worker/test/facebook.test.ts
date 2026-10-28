// Connecting a Facebook Page: the permissions Facebook really granted are checked, and with several Pages the owner
// chooses one before anything is saved. All network calls are mocked.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { encryptJson } from "../src/crypto";
import { handleFetch } from "../src/index";
import { clearSecretCache } from "../src/setup";
import type { Env } from "../src/supabase";

const KEY = "MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY=";
const env = (): Env => ({ SUPABASE_URL: "https://db.test", SUPABASE_SERVICE_ROLE_KEY: "service", SUPABASE_ANON_KEY: "anon",
  TOKEN_ENCRYPTION_KEY: KEY, DASHBOARD_URL: "https://dash.test", GITHUB_REPO: "me/studio", GITHUB_REF: "main", GITHUB_TOKEN: "gh",
  FACEBOOK_APP_ID: "app", FACEBOOK_APP_SECRET: "secret" } as Env);
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

const GRANTED = ["pages_show_list", "pages_read_engagement", "pages_manage_posts", "business_management"];
function facebook(opts: { granted?: string[]; declined?: string[]; pages: { id: string; name: string; tasks?: string[] }[]; savedPage?: string }) {
  routes.push((u) => (u.includes("/oauth/access_token") ? ok({ access_token: "user-token" }) : undefined));
  routes.push((u) => (u.includes("/me/permissions") ? ok({ data: [...(opts.granted ?? GRANTED).map((p) => ({ permission: p, status: "granted" })),
    ...(opts.declined ?? []).map((p) => ({ permission: p, status: "declined" }))] }) : undefined));
  routes.push((u) => (u.includes("/me/accounts") ? ok({ data: opts.pages.map((p) => ({ ...p, access_token: `tok-${p.id}` })) }) : undefined));
  routes.push((u, i) => (u.includes("/rest/v1/social_accounts") && (!i?.method || i.method === "GET") ? ok([{ external_id: opts.savedPage ?? null }]) : undefined));
}
async function callback() {
  const state = await encryptJson(KEY, { a: "acc1", p: "facebook", v: "n", e: Date.now() + 60_000 });
  return handleFetch(new Request(`https://w.test/oauth/facebook/callback?code=c&state=${encodeURIComponent(state)}`), env());
}
const saved = () => calls.filter((c) => c.url.includes("/rest/v1/oauth_connections") && c.init?.method === "PATCH").map((c) => JSON.parse(String(c.init!.body)));
const owner = () => {
  routes.push((u) => (u.includes("/auth/v1/user") ? ok({ id: "owner" }) : undefined));
  routes.push((u) => (u.includes("/rest/v1/app_owner") ? ok([{ user_id: "owner" }]) : undefined));
};

describe("Facebook connection", () => {
  it("saves the permissions Facebook actually granted and names the Page", async () => {
    facebook({ pages: [{ id: "p1", name: "Penny & Pixel", tasks: ["CREATE_CONTENT", "MANAGE"] }] });
    const res = await callback();
    expect(res.headers.get("Location")).toBe(`https://dash.test/settings?connected=facebook&page=${encodeURIComponent("Penny & Pixel (p1)")}`);
    expect(saved()[0].scopes).toEqual(GRANTED);
  });

  it("refuses when a needed permission was switched off, and says which", async () => {
    facebook({ granted: ["pages_show_list", "pages_read_engagement"], declined: ["pages_manage_posts"], pages: [{ id: "p1", name: "P" }] });
    const loc = decodeURIComponent((await callback()).headers.get("Location")!);
    expect(loc).toContain("connect_error=Facebook didn't allow: pages_manage_posts");
    expect(saved()).toEqual([]);
  });

  it("refuses a Page this login can't post on", async () => {
    facebook({ pages: [{ id: "p1", name: "Other Page", tasks: ["ANALYZE"] }] });
    expect(decodeURIComponent((await callback()).headers.get("Location")!)).toContain("can't post on Other Page");
    expect(saved()).toEqual([]);
  });

  it("with several Pages the owner chooses; nothing is saved until then", async () => {
    facebook({ pages: [{ id: "p1", name: "First" }, { id: "p2", name: "Second" }] });
    const loc = new URL((await callback()).headers.get("Location")!);
    expect(loc.pathname).toBe("/settings/accounts");
    const choice = loc.searchParams.get("pick_page")!;
    expect(choice).not.toContain("tok-p1");  // the Page tokens travel encrypted
    expect(saved()).toEqual([]);
    owner();
    const post = (path: string, body: unknown) => handleFetch(new Request(`https://w.test${path}`, { method: "POST", body: JSON.stringify(body), headers: { Authorization: "Bearer t" } }), env());
    expect(await (await post("/api/oauth/facebook-pages", { choice })).json()).toEqual({ pages: [{ id: "p1", name: "First" }, { id: "p2", name: "Second" }] });
    expect((await post("/api/oauth/facebook-page", { choice, page_id: "nope" })).status).toBe(400);
    expect(await (await post("/api/oauth/facebook-page", { choice, page_id: "p2" })).json()).toEqual({ page: "Second", id: "p2" });
    expect(saved()[0].status).toBe("connected");
  });

  it("reconnecting keeps the Page that was already connected", async () => {
    facebook({ pages: [{ id: "p1", name: "First" }, { id: "p2", name: "Second" }], savedPage: "p2" });
    expect((await callback()).headers.get("Location")).toContain("connected=facebook&page=Second");
  });

  it("choosing a Page needs the owner", async () => {
    routes.push((u) => (u.includes("/auth/v1/user") ? ok({ message: "bad" }, 401) : undefined));
    const res = await handleFetch(new Request("https://w.test/api/oauth/facebook-page", { method: "POST", body: '{"choice":"x","page_id":"p"}', headers: { Authorization: "Bearer x" } }), env());
    expect(res.status).toBe(401);
  });
});
