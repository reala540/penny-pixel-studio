import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { decryptJson, encryptJson } from "../src/crypto";
import { setAutoPost, dueIdeaSlot, handleCron, handleFetch, handleTelegram, localParts } from "../src/index";
import { clearSecretCache } from "../src/setup";
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
  clearSecretCache();
  vi.stubGlobal("fetch", async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    calls.push({ url, init });
    for (const r of routes) {
      const res = r(url, init);
      if (res) return res;
    }
    if (url.includes("api.telegram.org") && url.includes("/sendMessage")) return new Response(JSON.stringify({ok:true}),{status:200});
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
    expect(body.telegram.problem).toContain("rejected the bot token");
  });
});

describe("setup wizard", () => {
  const owner = () => {
    routes.push((u) => (u.includes("/auth/v1/user") ? ok({ id: "owner" }) : undefined));
    routes.push((u) => (u.includes("/rest/v1/app_owner") ? ok([{ user_id: "owner" }]) : undefined));
  };
  const post = (path: string, body: unknown, e = env(), auth = "Bearer t") =>
    handleFetch(new Request(`https://w.test/api/setup/${path}`, { method: "POST", body: JSON.stringify(body), headers: { Authorization: auth } }), e);

  it("refuses anyone but the owner", async () => {
    routes.push((u) => (u.includes("/auth/v1/user") ? ok({}, 401) : undefined));
    const res = await post("save", { name: "YOUTUBE_API_KEY", value: "AIzaSyExample1234" });
    expect(res.status).toBe(401);
    expect(calls.some((c) => c.url.includes("/rest/v1/app_secrets") && c.init?.method === "POST")).toBe(false);
  });

  it("encrypts a saved value, never returns it, audits only the hint, and tests it", async () => {
    owner();
    routes.push((u) => (u.includes("youtube/v3/videoCategories") ? ok({ items: [] }) : undefined));
    const res = await post("save", { name: "YOUTUBE_API_KEY", value: "  AIzaSyExample1234  " });
    const body = (await res.json()) as any;
    expect(res.status).toBe(200);
    expect(body).toMatchObject({ saved: true, hint: "••••1234", test: { ok: true } });
    expect(JSON.stringify(body)).not.toContain("AIzaSyExample1234");
    const write = calls.find((c) => c.url.includes("/rest/v1/app_secrets") && c.init?.method === "POST")!;
    const row = JSON.parse(String(write.init!.body));
    expect(row.name).toBe("YOUTUBE_API_KEY");
    expect(String(write.init!.body)).not.toContain("AIzaSyExample1234");
    expect(await decryptJson(KEY, row.ciphertext)).toEqual({ value: "AIzaSyExample1234" });
    const audit = calls.find((c) => c.url.includes("/rest/v1/audit_logs"))!;
    expect(String(audit.init!.body)).toContain("••••1234");
    expect(String(audit.init!.body)).not.toContain("AIzaSyExample1234");
  });

  it("rejects unknown names and badly pasted values with plain advice", async () => {
    owner();
    let res = await post("save", { name: "SUPABASE_DB_URL", value: "postgres://x" });
    expect(res.status).toBe(400);
    res = await post("save", { name: "TELEGRAM_BOT_TOKEN", value: "not a token" });
    expect(((await res.json()) as any).error).toContain("spaces");
    res = await post("save", { name: "GOOGLE_CLIENT_ID", value: "1234567890-abc" });
    expect(((await res.json()) as any).error).toContain("apps.googleusercontent.com");
  });

  it("saving a bot token makes a webhook secret and links the bot", async () => {
    owner();
    routes.push((u) => (u.includes("/getMe") ? ok({ ok: true, result: { username: "studio_bot" } }) : undefined));
    routes.push((u) => (u.includes("/setWebhook") ? ok({ ok: true }) : undefined));
    const e = env({ TELEGRAM_BOT_TOKEN: undefined, TELEGRAM_WEBHOOK_SECRET: undefined });
    const body = (await (await post("save", { name: "TELEGRAM_BOT_TOKEN", value: "123456789:AAExampleExampleExample_1" }, e)).json()) as any;
    expect(body.test).toEqual({ ok: true, detail: "Bot @studio_bot is ready." });
    expect(body.telegram).toEqual({ ok: true });
    const saved = calls.filter((c) => c.url.includes("/rest/v1/app_secrets") && c.init?.method === "POST").map((c) => JSON.parse(String(c.init!.body)).name);
    expect(saved).toEqual(["TELEGRAM_BOT_TOKEN", "TELEGRAM_WEBHOOK_SECRET"]);
    const hook = JSON.parse(String(calls.find((c) => c.url.includes("/setWebhook"))!.init!.body));
    expect(hook.secret_token).toMatch(/^[A-Za-z0-9_-]{20,}$/);
  });

  it("uses a dashboard-saved value instead of the GitHub one", async () => {
    owner();
    const ct = await encryptJson(KEY, { value: "999999999:AAFromTheDashboardSetupPage_x" });
    routes.push((u) => (u.includes("/rest/v1/app_secrets") ? ok([{ name: "TELEGRAM_BOT_TOKEN", ciphertext: ct, hint: "••••ge_x", updated_at: "2026-10-25T00:00:00Z" }]) : undefined));
    routes.push((u) => (u.includes("/getMe") ? ok({ ok: true, result: { username: "b" } }) : undefined));
    await post("test", { name: "TELEGRAM_BOT_TOKEN" });
    expect(calls.find((c) => c.url.includes("/getMe"))!.url).toContain("bot999999999:AAFromTheDashboardSetupPage_x/getMe");
  });

  it("Google: tells a wrong pair from a right one", async () => {
    owner();
    routes.push((u) => (u.includes("oauth2.googleapis.com") ? ok({ error: "invalid_grant" }, 400) : undefined));
    const e = env({ GOOGLE_CLIENT_ID: "1-a.apps.googleusercontent.com", GOOGLE_CLIENT_SECRET: "GOCSPX-secret" });
    expect(((await (await post("test", { name: "GOOGLE_CLIENT_ID" }, e)).json()) as any).test.ok).toBe(true);
    routes.unshift((u) => (u.includes("oauth2.googleapis.com") ? ok({ error: "invalid_client" }, 401) : undefined));
    expect(((await (await post("test", { name: "GOOGLE_CLIENT_SECRET" }, e)).json()) as any).test.ok).toBe(false);
    const missing = env({ GOOGLE_CLIENT_ID: "1-a.apps.googleusercontent.com", GOOGLE_CLIENT_SECRET: undefined });
    expect(((await (await post("test", { name: "GOOGLE_CLIENT_ID" }, missing)).json()) as any).test).toMatchObject({ ok: null });
  });

  it("status shows what is saved where, but never a value", async () => {
    owner();
    const ct = await encryptJson(KEY, { value: "AIzaSyFromDashboard9876" });
    routes.push((u) => (u.includes("/rest/v1/app_secrets") ? ok([{ name: "YOUTUBE_API_KEY", ciphertext: ct, hint: "••••9876", updated_at: "2026-10-25T00:00:00Z" },
      { name: "PEXELS_API_KEY", ciphertext: "broken", hint: "••••0000", updated_at: "2026-10-25T00:00:00Z" }]) : undefined));
    routes.push((u) => (u.includes("key=eq.engine_env_presence") ? ok([{ value: { names: { YOUTUBE_API_KEY: true, PEXELS_API_KEY: false }, checked_at: "2026-10-25T01:00:00Z" } }]) : undefined));
    routes.push((u) => (u.includes("api.github.com") ? ok({ workflows: [] }) : undefined));
    const body = (await (await post("status", {})).json()) as any;
    expect(body.core.database.ok).toBe(true);
    expect(body.core.encryption.ok).toBe(true);
    expect(body.core.github.ok).toBe(true);
    expect(body.values.YOUTUBE_API_KEY).toMatchObject({ dashboard: true, hint: "••••9876", github: true, readable: true });
    expect(body.values.PEXELS_API_KEY).toMatchObject({ dashboard: true, readable: false, github: false });
    expect(body.values.TELEGRAM_BOT_TOKEN).toMatchObject({ dashboard: false, github: true });
    expect(JSON.stringify(body)).not.toContain("AIzaSyFromDashboard9876");
    expect(body.core_names).toContain("TOKEN_ENCRYPTION_KEY");
  });

  it("the bot works with either the Setup-page or the GitHub webhook secret, nothing else", async () => {
    const ct = await encryptJson(KEY, { value: "dashboard-hook-secret" });
    routes.push((u) => (u.includes("/rest/v1/app_secrets") ? ok([{ name: "TELEGRAM_WEBHOOK_SECRET", ciphertext: ct, hint: null, updated_at: "x" }]) : undefined));
    const hook = (secret: string) => handleFetch(new Request("https://w.test/telegram/webhook", { method: "POST",
      headers: { "X-Telegram-Bot-Api-Secret-Token": secret }, body: JSON.stringify({ message: { text: "/help", chat: { id: 1 } } }) }), env());
    expect((await hook("dashboard-hook-secret")).status).toBe(200);
    expect((await hook("hook-secret")).status).toBe(200);
    expect((await hook("guess")).status).toBe(403);
  });

  it("removing a value falls back to GitHub and is audited", async () => {
    owner();
    const res = await post("remove", { name: "FRED_API_KEY" });
    expect(res.status).toBe(200);
    const del = calls.find((c) => c.init?.method === "DELETE")!;
    expect(del.url).toContain("app_secrets?name=eq.FRED_API_KEY");
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

  it("replaces a GitHub-secret key with one saved here and stops using the secret", async () => {
    owner();
    routes.push((u) => (u.includes("ai_providers?name=eq.mistral&select=key_env") ? ok([{ key_env: "MISTRAL_API_KEY" }]) : undefined));
    routes.push((u) => (u.includes("ai_providers?name=eq.mistral") && !u.includes("select=key_env") ? ok([{ name: "mistral", base_url: "https://m.test/v1" }]) : undefined));
    routes.push((u, i) => (u.endsWith("/rest/v1/ai_credentials") && i?.method === "POST" ? ok([{ id: "44444444-4444-4444-4444-444444444444" }], 201) : undefined));
    routes.push((u) => (u.includes("ai_credentials?id=eq.") ? ok([{ id: "44444444-4444-4444-4444-444444444444", key_hint: "••••zz9f" }]) : undefined));
    const res = await call("/api/credentials/replace-env", { provider: "mistral", key: KEY });
    expect(res.status).toBe(200);
    expect(await res.text()).not.toContain(KEY);
    const meta = JSON.parse(String(calls.find((c) => c.url.endsWith("/rest/v1/ai_credentials") && c.init?.method === "POST")!.init!.body));
    expect(meta).toMatchObject({ provider: "mistral", label: "Replaces MISTRAL_API_KEY", priority: 10 });
    const patch = calls.find((c) => c.url.includes("ai_providers?name=eq.mistral") && c.init?.method === "PATCH")!;
    expect(JSON.parse(String(patch.init!.body))).toMatchObject({ use_env_key: false });
    expect(calls.some((c) => c.url.includes("api.github.com"))).toBe(false);  // GitHub secrets are never touched
  });

  it("only replaces services that have a GitHub secret", async () => {
    owner();
    routes.push((u) => (u.includes("ai_providers?name=eq.xkiro&select=key_env") ? ok([{ key_env: null }]) : undefined));
    routes.push((u) => (u.includes("ai_providers?name=eq.xkiro") ? ok([{ name: "xkiro", base_url: "https://x.test/v1" }]) : undefined));
    const res = await call("/api/credentials/replace-env", { provider: "xkiro", key: KEY });
    expect(res.status).toBe(400);
    expect(calls.some((c) => c.url.endsWith("/rest/v1/ai_credentials") && c.init?.method === "POST")).toBe(false);
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

  it("tests a key with one short message when the provider has no model list (Cloudflare)", async () => {
    owner();
    const id = "22222222-2222-4222-8222-222222222222";
    const blob = await encryptJson(KEY_B64, { key: KEY });
    routes.push((u) => (u.includes(`ai_credentials?id=eq.${id}&select=provider`) ? ok([{ provider: "cloudflare2" }]) : undefined));
    routes.push((u) => (u.includes("ai_providers?name=eq.cloudflare2") ? ok([{ name: "cloudflare2", base_url: "https://cf.test/accounts/abc/ai/v1" }]) : undefined));
    routes.push((u) => (u.includes("ai_credential_secrets?credential_id") ? ok([{ ciphertext: blob }]) : undefined));
    routes.push((u) => (u.includes("ai_model_configs?provider=eq.cloudflare2") ? ok([{ model: "@cf/meta/llama-3.3-70b-instruct-fp8-fast" }]) : undefined));
    routes.push((u) => (u === "https://cf.test/accounts/abc/ai/v1/models" ? ok({}, 405) : undefined));
    routes.push((u, i) => (u === "https://cf.test/accounts/abc/ai/v1/chat/completions" && i?.method === "POST"
      ? (String((i?.headers as any)?.Authorization) === `Bearer ${KEY}` && JSON.parse(String(i.body)).model === "@cf/meta/llama-3.3-70b-instruct-fp8-fast"
        ? ok({ choices: [{ message: { content: "ready" } }] }) : ok({}, 401)) : undefined));
    const out = (await (await call("/api/credentials/test", { id })).json()) as any;
    expect(out).toMatchObject({ ok: true, message: "Key works · @cf/meta/llama-3.3-70b-instruct-fp8-fast answered" });
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

describe("Auto Review & Post switch", () => {
  const msg = (text: string, chat = 55) =>
    new Request("https://w.test/telegram/webhook", { method: "POST", headers: { "X-Telegram-Bot-Api-Secret-Token": "hook-secret" }, body: JSON.stringify({ message: { text, chat: { id: chat } } }) });
  const linked = () => routes.push((u) => (u.includes("key=eq.telegram_chat_id") ? ok([{ value: "55" }]) : undefined));
  const rpc = () => calls.filter((c) => c.url.includes("/rest/v1/rpc/set_auto_review_post"));
  const sent = () => calls.filter((c) => c.url.includes("/sendMessage")).map((c) => JSON.parse(String(c.init!.body)).text as string);

  it("shows the current mode, defaulting to OFF", async () => {
    linked();
    await handleTelegram(env(), msg("/autopost"));
    expect(sent()[0]).toContain("Auto Review &amp; Post: <b>OFF</b>");
    expect(rpc()).toHaveLength(0);
  });

  it("includes the mode in /status", async () => {
    linked();
    routes.push((u) => (u.includes("key=eq.auto_review_post") ? ok([{ value: true }]) : undefined));
    await handleTelegram(env(), msg("/status"));
    expect(sent()[0]).toContain("Auto Review &amp; Post: <b>ON</b>");
  });

  it("needs confirmation to switch ON from Telegram", async () => {
    linked();
    await handleTelegram(env(), msg("/autopost on"));
    expect(rpc()).toHaveLength(0);
    expect(sent()[0]).toContain("/autopost on confirm");
  });

  it("switches ON with confirmation through the audited function, then reviews what's waiting", async () => {
    linked();
    routes.push((u) => (u.includes("rpc/set_auto_review_post") ? ok({ on: true, was: false, reverted_posts: 0 }) : undefined));
    routes.push((u) => (u.includes("generation_jobs?on_conflict") ? ok([{ id: "j" }], 201) : undefined));
    routes.push((u) => (u.includes("api.github.com") ? new Response(null, { status: 204 }) : undefined));
    await handleTelegram(env(), msg("/autopost on confirm"));
    expect(JSON.parse(String(rpc()[0].init!.body))).toEqual({ p_on: true, p_actor: "telegram" });
    const job = calls.find((c) => c.url.includes("generation_jobs?on_conflict"))!;
    expect(JSON.parse(String(job.init!.body))).toMatchObject({ job_type: "auto_review", status: "queued", requested_by: "owner" });
    expect(calls.some((c) => c.url.includes("/actions/workflows/queue.yml/dispatches"))).toBe(true);
    expect(sent().some((t) => t.includes("Auto Review &amp; Post: ON</b> (from Telegram)"))).toBe(true);
  });

  it("switches OFF immediately and reports posts returned to review", async () => {
    linked();
    routes.push((u) => (u.includes("rpc/set_auto_review_post") ? ok({ on: false, was: true, reverted_posts: 3 }) : undefined));
    await handleTelegram(env(), msg("/autopost off"));
    expect(JSON.parse(String(rpc()[0].init!.body))).toEqual({ p_on: false, p_actor: "telegram" });
    expect(sent().some((t) => t.includes("OFF") && t.includes("3 auto-approved post(s)"))).toBe(true);
    expect(calls.some((c) => c.url.includes("generation_jobs"))).toBe(false);
  });

  it("ignores the command from any other chat", async () => {
    routes.push((u) => (u.includes("key=eq.telegram_chat_id") ? ok([{ value: "999" }]) : undefined));
    await handleTelegram(env(), msg("/autopost on confirm"));
    expect(rpc()).toHaveLength(0);
  });

  it("reports the saved mode even when Telegram can't be reached", async () => {
    routes.push((u) => (u.includes("/auth/v1/user") ? ok({ id: "owner" }) : undefined));
    routes.push((u) => (u.includes("/rest/v1/app_owner") ? ok([{ user_id: "owner" }]) : undefined));
    routes.push((u) => (u.includes("key=eq.telegram_chat_id") ? ok([{ value: "55" }]) : undefined));
    routes.push((u) => (u.includes("rpc/set_auto_review_post") ? ok({ on: false, was: true, reverted_posts: 0 }) : undefined));
    routes.push((u) => { if (u.includes("api.telegram.org")) throw new TypeError("fetch failed"); return undefined; });
    const res = await handleFetch(new Request("https://w.test/api/autopost", { method: "POST", body: JSON.stringify({ on: false }), headers: { Authorization: "Bearer t" } }), env());
    expect(res.status).toBe(200);
    expect(await res.json()).toMatchObject({ on: false, notified: false });
  });

  it("dashboard endpoint is owner-only and requires confirmation for ON", async () => {
    const call = (body: unknown) => handleFetch(new Request("https://w.test/api/autopost", { method: "POST", body: JSON.stringify(body), headers: { Authorization: "Bearer t" } }), env());
    routes.push((u) => (u.includes("/auth/v1/user") ? ok({ message: "bad" }, 401) : undefined));
    expect((await call({ on: false })).status).toBe(401);
    routes.length = 0;
    routes.push((u) => (u.includes("/auth/v1/user") ? ok({ id: "owner" }) : undefined));
    routes.push((u) => (u.includes("/rest/v1/app_owner") ? ok([{ user_id: "owner" }]) : undefined));
    routes.push((u) => (u.includes("rpc/set_auto_review_post") ? ok({ on: false, was: false, reverted_posts: 0 }) : undefined));
    expect((await call({ on: true })).status).toBe(400);
    expect(rpc()).toHaveLength(0);
    const res = await call({ on: false });
    expect(res.status).toBe(200);
    expect(JSON.parse(String(rpc()[0].init!.body))).toEqual({ p_on: false, p_actor: "owner" });
  });
});

describe("Stop & clear", () => {
  const asOwner = () => {
    routes.push((u) => (u.includes("/auth/v1/user") ? ok({ id: "owner" }) : undefined));
    routes.push((u) => (u.includes("/rest/v1/app_owner") ? ok([{ user_id: "owner" }]) : undefined));
  };
  const press = () => handleFetch(new Request("https://w.test/api/stop-clear", { method: "POST", headers: { Authorization: "Bearer t" } }), env());

  it("needs the owner", async () => {
    routes.push((u) => (u.includes("/auth/v1/user") ? ok({ message: "bad" }, 401) : undefined));
    const res = await press();
    expect(res.status).toBe(401);
    expect(calls.some((c) => c.url.includes("api.github.com") || c.url.includes("rpc/stop_and_clear"))).toBe(false);
  });

  it("cancels content runs (never publishing), clears the database and removes the files", async () => {
    asOwner();
    routes.push((u) => (u.includes("/actions/runs?status=in_progress") ? ok({ workflow_runs: [
      { id: 1, path: ".github/workflows/queue.yml", status: "in_progress" },
      { id: 2, path: ".github/workflows/publish.yml", status: "in_progress" }] }) : undefined));
    routes.push((u, i) => (u.includes("/actions/runs/1/cancel") && i?.method === "POST" ? new Response(null, { status: 202 }) : undefined));
    routes.push((u) => (u.includes("rpc/stop_and_clear") ? ok({ stopped: true, jobs_stopped: 3, packages: 1, ideas: 6,
      sources: 9, notifications: 2, storage_paths: ["projects/p1/preview.mp4", "projects/p1/thumb.png"] }) : undefined));
    const res = await press();
    expect(res.status).toBe(200);
    const body = (await res.json()) as Record<string, unknown>;
    expect(body).toMatchObject({ stopped: true, runs_cancelled: 1, jobs_stopped: 3, packages: 1, ideas: 6, files_removed: 2 });
    expect(body.storage_paths).toBeUndefined();
    expect(calls.some((c) => c.url.includes("/actions/runs/2/cancel"))).toBe(false); // an upload is never cut off
    const del = calls.find((c) => c.url.endsWith("/storage/v1/object/studio"))!;
    expect(del.init?.method).toBe("DELETE");
    expect(JSON.parse(String(del.init?.body))).toEqual({ prefixes: ["projects/p1/preview.mp4", "projects/p1/thumb.png"] });
    expect(calls.some((c) => c.url.includes("/rest/v1/audit_logs"))).toBe(true);
  });

  it("says so when nothing is running", async () => {
    asOwner();
    routes.push((u) => (u.includes("rpc/stop_and_clear") ? ok({ stopped: false, reason: "nothing is running" }) : undefined));
    const body = (await (await press()).json()) as Record<string, unknown>;
    expect(body).toMatchObject({ stopped: false, reason: "nothing is running", files_removed: 0 });
    expect(calls.some((c) => c.url.includes("/storage/v1/object"))).toBe(false);
  });
});

describe("held packages", () => {
  it("wakes the engine when a reminder or replacement is due, at most hourly", async () => {
    const past = new Date(Date.now() - 60_000).toISOString();
    routes.push((u) => (u.includes("key=eq.auto_replace_next_at") ? ok([{ value: past }]) : undefined));
    routes.push((u) => (u.includes("api.github.com") ? new Response(null, { status: 204 }) : undefined));
    expect((await handleCron(env())).queue).toBe(true);
    routes.unshift((u) => (u.includes("key=eq.last_queue_dispatch") ? ok([{ value: new Date().toISOString() }]) : undefined));
    expect((await handleCron(env())).queue).toBeUndefined();
  });
});


describe("delivery acknowledgement",()=>{
  it("persists an approval-mode alert when Telegram rejects delivery",async()=>{
    routes.push((u)=>u.includes("rpc/set_auto_review_post") ? ok({on:false,was:true,reverted_posts:0}) : u.includes("key=eq.telegram_chat_id") ? ok([{value:"55"}]) : u.includes("api.telegram.org") ? ok({ok:false},429) : undefined);
    const result=await setAutoPost(env(),false,"owner");
    expect(result.notified).toBe(false);
    const saved=calls.find(c=>c.url.endsWith("/rest/v1/notifications") && c.init?.method === "POST");
    expect(saved).toBeDefined();expect(JSON.parse(String(saved!.init!.body)).kind).toBe("approval_mode");
  });
});

describe("scheduled retries", () => {
  it("wakes the engine when a step's retry is due, without dispatching on every tick", async () => {
    routes.push((u) => (u.includes("generation_jobs") && u.includes("status=eq.retrying") ? ok([{ id: "stage-1" }]) : undefined));
    routes.push((u) => (u.includes("api.github.com") ? new Response(null, { status: 204 }) : undefined));
    expect((await handleCron(env())).queue).toBe(true);
    routes.unshift((u) => (u.includes("key=eq.last_queue_dispatch") ? ok([{ value: new Date().toISOString() }]) : undefined));
    expect((await handleCron(env())).queue).toBeUndefined();
  });
});
