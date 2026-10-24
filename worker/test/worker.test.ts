import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { decryptJson, encryptJson } from "../src/crypto";
import { handleCron, handleFetch, handleTelegram } from "../src/index";
import type { Env } from "../src/supabase";

const KEY = "MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY="; // same test key as the Python suite

function env(extra: Partial<Env> = {}): Env {
  return {
    SUPABASE_URL: "https://db.test",
    SUPABASE_SERVICE_ROLE_KEY: "service",
    SUPABASE_ANON_KEY: "anon",
    TOKEN_ENCRYPTION_KEY: KEY,
    DASHBOARD_URL: "https://dash.test",
    GITHUB_REPO: "me/studio",
    GITHUB_REF: "main",
    GITHUB_TOKEN: "gh",
    TELEGRAM_BOT_TOKEN: "bot",
    TELEGRAM_WEBHOOK_SECRET: "hook-secret",
    ...extra,
  };
}

type Route = (url: string, init?: RequestInit) => Response | undefined;
let routes: Route[] = [];
const calls: { url: string; init?: RequestInit }[] = [];

beforeEach(() => {
  routes = [];
  calls.length = 0;
  vi.stubGlobal("fetch", async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    calls.push({ url, init });
    for (const r of routes) {
      const res = r(url, init);
      if (res) return res;
    }
    return new Response("[]", { status: 200 });
  });
});
afterEach(() => vi.unstubAllGlobals());

const ok = (data: unknown, status = 200) => new Response(JSON.stringify(data), { status });

describe("crypto", () => {
  it("round-trips tokens in the shared format", async () => {
    const blob = await encryptJson(KEY, { access_token: "abc" });
    expect(await decryptJson(KEY, blob)).toEqual({ access_token: "abc" });
  });
});

describe("dashboard API", () => {
  it("rejects dispatch without an owner session", async () => {
    routes.push((u) => (u.includes("/auth/v1/user") ? ok({ message: "bad" }, 401) : undefined));
    const res = await handleFetch(new Request("https://w.test/api/dispatch", { method: "POST", body: '{"workflow":"queue"}', headers: { Authorization: "Bearer nope" } }), env());
    expect(res.status).toBe(401);
    expect(calls.some((c) => c.url.includes("api.github.com"))).toBe(false);
  });

  it("rejects a signed-in user who is not the owner", async () => {
    routes.push((u) => (u.includes("/auth/v1/user") ? ok({ id: "stranger" }) : undefined));
    routes.push((u) => (u.includes("/rest/v1/app_owner") ? ok([]) : undefined));
    const res = await handleFetch(new Request("https://w.test/api/dispatch", { method: "POST", body: '{"workflow":"queue"}', headers: { Authorization: "Bearer t" } }), env());
    expect(res.status).toBe(401);
  });

  it("dispatches a known workflow for the owner", async () => {
    routes.push((u) => (u.includes("/auth/v1/user") ? ok({ id: "owner" }) : undefined));
    routes.push((u) => (u.includes("/rest/v1/app_owner") ? ok([{ user_id: "owner" }]) : undefined));
    routes.push((u) => (u.includes("api.github.com") ? new Response(null, { status: 204 }) : undefined));
    const res = await handleFetch(new Request("https://w.test/api/dispatch", { method: "POST", body: '{"workflow":"produce"}', headers: { Authorization: "Bearer t" } }), env());
    expect(res.status).toBe(200);
    const gh = calls.find((c) => c.url.includes("api.github.com"))!;
    expect(gh.url).toContain("/actions/workflows/weekly-produce.yml/dispatches");
  });

  it("builds an OAuth URL with encrypted state", async () => {
    routes.push((u) => (u.includes("/auth/v1/user") ? ok({ id: "owner" }) : undefined));
    routes.push((u) => (u.includes("/rest/v1/app_owner") ? ok([{ user_id: "owner" }]) : undefined));
    routes.push((u) => (u.includes("/rest/v1/social_accounts") ? ok([{ id: "acc1", platform: "x" }]) : undefined));
    const res = await handleFetch(new Request("https://w.test/api/oauth/start", { method: "POST", body: '{"account_id":"acc1"}', headers: { Authorization: "Bearer t" } }), env({ X_CLIENT_ID: "cid" }));
    const { url } = (await res.json()) as { url: string };
    const u = new URL(url);
    expect(u.host).toBe("x.com");
    expect(u.searchParams.get("code_challenge_method")).toBe("S256");
    const state = await decryptJson<{ a: string; p: string }>(KEY, u.searchParams.get("state")!);
    expect(state).toMatchObject({ a: "acc1", p: "x" });
  });

  it("rejects an OAuth callback with forged state", async () => {
    const res = await handleFetch(new Request("https://w.test/oauth/x/callback?code=c&state=forged"), env());
    expect(res.status).toBe(302);
    expect(res.headers.get("location")).toContain("connect_error");
  });
});

describe("telegram", () => {
  const msg = (text: string, chat = 55) =>
    new Request("https://w.test/telegram/webhook", { method: "POST", headers: { "X-Telegram-Bot-Api-Secret-Token": "hook-secret" }, body: JSON.stringify({ message: { text, chat: { id: chat } } }) });

  it("rejects requests without the webhook secret", async () => {
    const res = await handleTelegram(env(), new Request("https://w.test/telegram/webhook", { method: "POST", body: "{}" }));
    expect(res.status).toBe(403);
  });

  it("ignores commands from an unlinked chat", async () => {
    routes.push((u) => (u.includes("key=eq.telegram_chat_id") ? ok([{ value: "999" }]) : undefined));
    await handleTelegram(env(), msg("/pause"));
    expect(calls.some((c) => c.url.includes("rest/v1/settings?on_conflict"))).toBe(false);
    const sent = calls.find((c) => c.url.includes("api.telegram.org"))!;
    expect(String(sent.init?.body)).toContain("private");
  });

  it("pauses for the linked owner chat and needs confirmation to resume", async () => {
    routes.push((u) => (u.includes("key=eq.telegram_chat_id") ? ok([{ value: "55" }]) : undefined));
    await handleTelegram(env(), msg("/pause"));
    const write = calls.find((c) => c.url.includes("rest/v1/settings?on_conflict"))!;
    expect(String(write.init?.body)).toContain('"paused"');
    calls.length = 0;
    await handleTelegram(env(), msg("/resume"));
    expect(calls.some((c) => c.url.includes("rest/v1/settings?on_conflict"))).toBe(false);
  });

  it("links a chat with the one-time code", async () => {
    routes.push((u) => (u.includes("key=eq.telegram_chat_id") ? ok([]) : undefined));
    routes.push((u) => (u.includes("key=eq.telegram_link_code") ? ok([{ value: "ABC123" }]) : undefined));
    await handleTelegram(env(), msg("/link ABC123", 77));
    const writes = calls.filter((c) => c.url.includes("rest/v1/settings?on_conflict")).map((c) => String(c.init?.body));
    expect(writes.some((b) => b.includes('"telegram_chat_id"') && b.includes('"77"'))).toBe(true);
  });
});

describe("telegram connection", () => {
  const owner = () => {
    routes.push((u) => (u.includes("/auth/v1/user") ? ok({ id: "owner" }) : undefined));
    routes.push((u) => (u.includes("/rest/v1/app_owner") ? ok([{ user_id: "owner" }]) : undefined));
  };
  const linkCode = (e: Env) =>
    handleFetch(new Request("https://w.test/api/telegram/link-code", { method: "POST", body: "{}", headers: { Authorization: "Bearer t" } }), e);

  it("points the bot at this Worker when a link code is requested", async () => {
    owner();
    routes.push((u) => (u.includes("/setWebhook") ? ok({ ok: true, result: true }) : undefined));
    const res = await linkCode(env());
    const body = (await res.json()) as any;
    expect(body.code).toMatch(/^[A-Z0-9]+$/);
    expect(body.telegram).toEqual({ ok: true });
    const hook = calls.find((c) => c.url.includes("/setWebhook"))!;
    expect(JSON.parse(String(hook.init!.body))).toMatchObject({ url: "https://w.test/telegram/webhook", secret_token: "hook-secret" });
  });

  it("explains a webhook secret Telegram would refuse, without calling Telegram", async () => {
    owner();
    const body = (await (await linkCode(env({ TELEGRAM_WEBHOOK_SECRET: "has spaces!" }))).json()) as any;
    expect(body.telegram.ok).toBe(false);
    expect(body.telegram.problem).toContain("letters, numbers");
    expect(calls.some((c) => c.url.includes("api.telegram.org"))).toBe(false);
  });

  it("ignores whitespace pasted around the webhook secret", async () => {
    owner();
    routes.push((u) => (u.includes("/setWebhook") ? ok({ ok: true }) : undefined));
    const body = (await (await linkCode(env({ TELEGRAM_WEBHOOK_SECRET: " hook-secret\n" }))).json()) as any;
    expect(body.telegram).toEqual({ ok: true });
    const hook = calls.find((c) => c.url.includes("/setWebhook"))!;
    expect(JSON.parse(String(hook.init!.body)).secret_token).toBe("hook-secret");
  });

  it("explains a wrong bot token", async () => {
    owner();
    routes.push((u) => (u.includes("/setWebhook") ? ok({ ok: false, description: "Unauthorized" }, 401) : undefined));
    const body = (await (await linkCode(env())).json()) as any;
    expect(body.telegram.problem).toContain("TELEGRAM_BOT_TOKEN");
  });
});

describe("cron", () => {
  it("does nothing (spends no GitHub minutes) when nothing is due", async () => {
    const out = await handleCron(env());
    expect(out).toEqual({});
    expect(calls.some((c) => c.url.includes("api.github.com"))).toBe(false);
  });

  it("dispatches publish when a post is due and not paused", async () => {
    routes.push((u) => (u.includes("rest/v1/scheduled_posts") ? ok([{ id: "p1" }]) : undefined));
    routes.push((u) => (u.includes("key=eq.paused") ? ok([{ value: false }]) : undefined));
    routes.push((u) => (u.includes("api.github.com") ? new Response(null, { status: 204 }) : undefined));
    const out = await handleCron(env());
    expect(out.publish).toBe(true);
  });

  it("respects the pause switch", async () => {
    routes.push((u) => (u.includes("rest/v1/scheduled_posts") ? ok([{ id: "p1" }]) : undefined));
    routes.push((u) => (u.includes("key=eq.paused") ? ok([{ value: true }]) : undefined));
    const out = await handleCron(env());
    expect(out.publish).toBeUndefined();
  });
});
