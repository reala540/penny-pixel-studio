import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { decryptJson, encryptJson } from "../src/crypto";
import { dueIdeaSlot, handleCron, handleFetch, handleTelegram, localParts } from "../src/index";
import type { Env } from "../src/supabase";

const KEY = "MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY="; // same test key as the Python suite
const KEY_B64 = KEY;

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
    // settings.value is NOT NULL in the real schema: reject null writes like PostgREST would.
    routes.push((u, init) => (u.includes("rest/v1/settings?on_conflict") && String(init?.body).includes('"value":null') ? ok({ code: "23502" }, 400) : undefined));
    await handleTelegram(env(), msg("/link ABC123", 77));
    const writes = calls.filter((c) => c.url.includes("rest/v1/settings?on_conflict")).map((c) => String(c.init?.body));
    expect(writes.some((b) => b.includes('"telegram_chat_id"') && b.includes('"77"'))).toBe(true);
    expect(calls.some((c) => c.init?.method === "DELETE" && c.url.includes("key=eq.telegram_link_code"))).toBe(true);
    const reply = calls.find((c) => c.url.includes("/sendMessage"))!;
    expect(String(reply.init!.body)).toContain("Linked!");
  });

  it("answers 200 even when a command fails, so Telegram doesn't resend it", async () => {
    routes.push((u) => (u.includes("rest/v1/settings?key=eq.telegram_chat_id") ? ok({ message: "down" }, 500) : undefined));
    const res = await handleTelegram(env(), msg("/status", 77));
    expect(res.status).toBe(200);
    expect(String(calls.find((c) => c.url.includes("/sendMessage"))!.init!.body)).toContain("went wrong");
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

describe("AI API Manager", () => {
  const owner = () => {
    routes.push((u) => (u.includes("/auth/v1/user") ? ok({ id: "owner" }) : undefined));
    routes.push((u) => (u.includes("/rest/v1/app_owner") ? ok([{ user_id: "owner" }]) : undefined));
  };
  const call = (path: string, body: unknown, e = env()) =>
    handleFetch(new Request(`https://w.test${path}`, { method: "POST", body: JSON.stringify(body), headers: { Authorization: "Bearer t" } }), e);
  const KEY = "AIzaSy-secret-key-1234567890-zz9f";

  it("refuses everyone but the owner", async () => {
    routes.push((u) => (u.includes("/auth/v1/user") ? ok({ message: "bad" }, 401) : undefined));
    const res = await call("/api/credentials/add", { provider: "gemini", key: KEY });
    expect(res.status).toBe(401);
    expect(calls.some((c) => c.url.includes("ai_credential"))).toBe(false);
  });

  it("encrypts a new key server-side and only ever returns a masked hint", async () => {
    owner();
    routes.push((u, i) => (u.includes("ai_providers?name=eq.gemini") ? ok([{ name: "gemini", base_url: "https://g.test/v1" }]) : undefined));
    routes.push((u, i) => (u.endsWith("/rest/v1/ai_credentials") && i?.method === "POST" ? ok([{ id: "11111111-1111-1111-1111-111111111111" }], 201) : undefined));
    routes.push((u) => (u.includes("ai_credentials?id=eq.") ? ok([{ id: "11111111-1111-1111-1111-111111111111", key_hint: "••••zz9f", label: "Sam's key" }]) : undefined));
    const res = await call("/api/credentials/add", { provider: "gemini", key: KEY, label: "Sam's key", owner_name: "Sam",
      authorized_use: "Studio scripts", authorized: true });
    const text = await res.text();
    expect(res.status).toBe(200);
    expect(text).not.toContain(KEY);
    expect(text).toContain("••••zz9f");
    const meta = calls.find((c) => c.url.endsWith("/rest/v1/ai_credentials") && c.init?.method === "POST")!;
    expect(String(meta.init!.body)).not.toContain(KEY);
    expect(JSON.parse(String(meta.init!.body))).toMatchObject({ key_hint: "••••zz9f", quota_group: "gemini", separate_account_attested: false });
    const secret = calls.find((c) => c.url.endsWith("/rest/v1/ai_credential_secrets"))!;
    const blob = JSON.parse(String(secret.init!.body)).ciphertext;
    expect(String(secret.init!.body)).not.toContain(KEY);
    expect(await decryptJson(KEY_B64, blob)).toEqual({ key: KEY });
  });

  it("requires the owner's authorisation and validates input", async () => {
    owner();
    routes.push((u) => (u.includes("ai_providers?name=eq.gemini") ? ok([{ name: "gemini", base_url: "https://g.test/v1" }]) : undefined));
    const noAuth = await call("/api/credentials/add", { provider: "gemini", key: KEY, label: "x", owner_name: "x", authorized_use: "abc" });
    expect(noAuth.status).toBe(400);
    expect(((await noAuth.json()) as any).error).toContain("authorised");
    const shortKey = await call("/api/credentials/add", { provider: "gemini", key: "abc", authorized: true });
    expect(shortKey.status).toBe(400);
  });

  it("gives an attested separate account its own quota group", async () => {
    owner();
    routes.push((u) => (u.includes("ai_providers?name=eq.gemini") ? ok([{ name: "gemini", base_url: "https://g.test/v1" }]) : undefined));
    routes.push((u, i) => (u.endsWith("/rest/v1/ai_credentials") && i?.method === "POST" ? ok([{ id: "22222222-2222-2222-2222-222222222222" }], 201) : undefined));
    await call("/api/credentials/add", { provider: "gemini", key: KEY, label: "Family", owner_name: "Ann",
      authorized_use: "Studio", authorized: true, separate_account: true });
    const meta = JSON.parse(String(calls.find((c) => c.url.endsWith("/rest/v1/ai_credentials") && c.init?.method === "POST")!.init!.body));
    expect(meta.quota_group).toMatch(/^gemini:[0-9a-f]{8}$/);
    expect(meta.separate_account_attested).toBe(true);
  });

  it("tests a stored key against the provider's model list without exposing it", async () => {
    owner();
    const id = "33333333-3333-3333-3333-333333333333";
    const blob = await encryptJson(KEY_B64, { key: KEY });
    routes.push((u) => (u.includes(`ai_credentials?id=eq.${id}&select=provider`) ? ok([{ provider: "gemini" }]) : undefined));
    routes.push((u) => (u.includes("ai_providers?name=eq.gemini") ? ok([{ name: "gemini", base_url: "https://g.test/v1/" }]) : undefined));
    routes.push((u) => (u.includes("ai_credential_secrets?credential_id") ? ok([{ ciphertext: blob }]) : undefined));
    routes.push((u, i) => (u === "https://g.test/v1/models" ? (String((i?.headers as any)?.Authorization) === `Bearer ${KEY}` ? ok({ data: [{ id: "gemini-3.8-flash" }] }) : ok({}, 401)) : undefined));
    const res = await call("/api/credentials/test", { id });
    const out = (await res.json()) as any;
    expect(out).toMatchObject({ ok: true, models: ["gemini-3.8-flash"] });
    expect(JSON.stringify(out)).not.toContain(KEY);
    const patch = calls.find((c) => c.url.includes(`ai_credentials?id=eq.${id}`) && c.init?.method === "PATCH")!;
    expect(JSON.parse(String(patch.init!.body)).health).toBe("healthy");
  });

  it("only accepts public https provider addresses", async () => {
    owner();
    for (const base of ["http://api.example.com/v1", "https://127.0.0.1/v1", "https://localhost/v1", "https://user:pw@api.example.com"]) {
      const res = await call("/api/providers/add", { name: "custom", base_url: base, models: [{ id: "m", roles: ["critic"] }] });
      expect(res.status).toBe(400);
    }
  });
});

describe("scheduled idea generation", () => {
  it("knows the studio's local day and hour", () => {
    const p = localParts(new Date("2026-10-26T05:30:00Z"), "Africa/Nairobi");  // Monday 08:30 in Nairobi
    expect(p).toEqual({ date: "2026-10-26", weekday: 0, hour: 8 });
  });

  it("is due once per slot, only on chosen days after the chosen hour", () => {
    const mon0830 = new Date("2026-10-26T05:30:00Z");
    expect(dueIdeaSlot({ frequency: "manual" }, mon0830, "Africa/Nairobi")).toBeNull();
    expect(dueIdeaSlot({ frequency: "daily", hour: 9 }, mon0830, "Africa/Nairobi")).toBeNull();
    expect(dueIdeaSlot({ frequency: "daily", hour: 8 }, mon0830, "Africa/Nairobi")).toBe("ideas:auto:2026-10-26");
    expect(dueIdeaSlot({ frequency: "weekly", weekdays: [2], hour: 8 }, mon0830, "Africa/Nairobi")).toBeNull();
    expect(dueIdeaSlot({ frequency: "custom", weekdays: [0, 3], hour: 7 }, mon0830, "Africa/Nairobi")).toBe("ideas:auto:2026-10-26");
  });

  it("queues one idea job per slot and dispatches it", async () => {
    vi.setSystemTime(new Date("2026-10-26T05:30:00Z"));
    routes.push((u) => (u.includes("key=eq.idea_generator") ? ok([{ value: { frequency: "daily", hour: 6 } }]) : undefined));
    routes.push((u, i) => (u.includes("rest/v1/generation_jobs?on_conflict") ? ok([{ id: "j1" }], 201) : undefined));
    routes.push((u) => (u.includes("generation_jobs?select=id&status=eq.queued") ? ok([{ id: "j1" }]) : undefined));
    routes.push((u) => (u.includes("api.github.com") ? new Response(null, { status: 204 }) : undefined));
    const out = await handleCron(env());
    vi.useRealTimers();
    expect(out).toMatchObject({ ideas: true, queue: true });
    const ins = calls.find((c) => c.url.includes("generation_jobs?on_conflict=idempotency_key"))!;
    expect(String((ins.init!.headers as any).Prefer)).toContain("ignore-duplicates");
    expect(JSON.parse(String(ins.init!.body))).toMatchObject({ job_type: "generate_ideas", idempotency_key: "ideas:auto:2026-10-26" });
  });
});
