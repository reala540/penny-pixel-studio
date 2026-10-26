// Test harness: runs the real dashboard against a simulated database and Worker (nothing leaves this machine).
// Each scenario can make tables fail, answer slowly, go offline or expire the sign-in.
import { spawn } from "node:child_process";
import { setTimeout as sleep } from "node:timers/promises";
import { createRequire } from "node:module";

// Playwright comes pre-installed on the machine (not a dashboard dependency), so load it through require.
const { chromium } = createRequire(import.meta.url)("playwright");

export const SUPABASE = "https://mock-supabase.test";
export const WORKER = "https://mock-worker.test";
export const PORT = Number(process.env.E2E_PORT || 5179);
export const BASE = `http://127.0.0.1:${PORT}`;
export const OWNER = { id: "00000000-0000-4000-8000-000000000001", email: "owner@studio.test" };

/** Start the dashboard dev server pointed at the simulated services. */
export async function startServer() {
  const child = spawn("npx", ["vite", "--port", String(PORT), "--strictPort", "--host", "127.0.0.1"], {
    cwd: new URL("..", import.meta.url).pathname,
    env: { ...process.env, VITE_SUPABASE_URL: SUPABASE, VITE_SUPABASE_ANON_KEY: "test-anon-key", VITE_WORKER_URL: WORKER },
    stdio: ["ignore", "pipe", "pipe"],
  });
  for (let i = 0; i < 120; i++) {
    try { if ((await fetch(BASE)).ok) return child; } catch { /* not up yet */ }
    await sleep(500);
  }
  child.kill();
  throw new Error("dashboard dev server didn't start");
}

const iso = (minutes) => new Date(Date.now() + minutes * 60_000).toISOString();

/** Sample data: a small, realistic studio. */
export function seed() {
  return {
    settings: { paused: false, auto_review_post: false, timezone: "Africa/Nairobi", telegram_chat_id: "12345",
      provider_check: { checked_at: iso(-60), results: [{ provider: "groq", status: "ok", note: "1 of 1 models work" }] }, tour_done: true,
      setup_progress: { schedule_reviewed: true } },
    social_accounts: [
      { id: "acc-yt-ai", platform: "youtube", label: "YouTube AI", handle: "@pennypixelai", enabled: true, topic_mix: {}, weekly_targets: {},
        oauth_connections: { status: "connected", last_error: null, token_expires_at: iso(600), app_publish_mode: "unverified" } },
      { id: "acc-x", platform: "x", label: "X", handle: null, enabled: true, topic_mix: {}, weekly_targets: {},
        oauth_connections: { status: "disconnected", last_error: null, token_expires_at: null, app_publish_mode: "unverified" } },
    ],
    content_projects: [
      { id: "proj-1", title: "How to write better prompts for ChatGPT", channel_slug: "ai", format: "long", status: "ready_for_review",
        parent_project_id: null, created_at: iso(-90), updated_at: iso(-30), quality_report: {}, recipe: {} },
    ],
    generation_jobs: [
      { id: "job-1", job_type: "produce_idea", status: "running", progress: { label: "Writing the script and checking the facts", step: 1, total: 4 },
        input: { channel: "ai" }, error_message: null, requested_by: "owner", created_at: iso(-12), started_at: iso(-11), updated_at: iso(-1),
        finished_at: null, project_id: "proj-1", content_projects: { title: "How to write better prompts for ChatGPT" } },
    ],
    scheduled_posts: [], notifications: [], audit_logs: [], generated_ideas: [], content_ideas: [], idea_runs: [],
    ai_providers: [{ name: "groq", enabled: true, last_error: null, last_success_at: iso(-60), circuit_open_until: null }],
    ai_model_configs: [], ai_credentials: [], budgets: [], budget_reservations: [], channel_profiles: [], manual_tasks: [],
    published_posts: [], auto_reviews: [], approvals: [], research_sources: [], provider_usage: [],
  };
}

/** Return rows for a PostgREST-style request, honouring the simple filters the dashboard uses. */
function answer(db, table, url) {
  let rows = db[table] ?? [];
  for (const [k, v] of url.searchParams) {
    if (["select", "order", "limit", "offset", "or"].includes(k)) continue;
    const [op, ...rest] = v.split(".");
    const val = rest.join(".");
    const get = (r) => (k.includes("->>") ? k.split("->>").reduce((o, part) => o?.[part.replace(/^->/, "")], r) : r[k]);
    if (op === "eq") rows = rows.filter((r) => String(get(r)) === val);
    if (op === "in") { const set = val.replace(/^\(|\)$/g, "").split(",").map((x) => x.replace(/"/g, "")); rows = rows.filter((r) => set.includes(String(get(r)))); }
    if (op === "is" && val === "null") rows = rows.filter((r) => get(r) == null);
  }
  const order = url.searchParams.get("order");
  if (order) { const [col, dir] = order.split("."); rows = [...rows].sort((a, b) => String(a[col]).localeCompare(String(b[col])) * (dir === "desc" ? -1 : 1)); }
  const limit = Number(url.searchParams.get("limit") || 0);
  return limit ? rows.slice(0, limit) : rows;
}

/**
 * Open a page with the simulated services.
 * opts: { signedIn = true, userId, fail = { table|"*"|"rpc:name"|"worker:path": status }, slow = { table: ms }, db, viewport, onRequest }
 */
export async function openStudio(browser, path = "/", opts = {}) {
  const db = opts.db ?? seed();
  const context = await browser.newContext({ viewport: opts.viewport ?? { width: 1366, height: 900 }, serviceWorkers: "block" });
  const calls = [];
  if (opts.signedIn !== false) {
    const session = { access_token: "test-access", refresh_token: "test-refresh", token_type: "bearer", expires_in: 3600,
      expires_at: Math.floor(Date.now() / 1000) + (opts.sessionSeconds ?? 3600), user: { id: opts.userId ?? OWNER.id, email: OWNER.email, aud: "authenticated", role: "authenticated" } };
    await context.addInitScript(([k, v]) => { try { localStorage.setItem(k, v); } catch { /* ignore */ } }, ["sb-mock-supabase-auth-token", JSON.stringify(session)]);
  }
  await context.route(`${SUPABASE}/**`, async (route) => {
    const req = route.request();
    const url = new URL(req.url());
    const path = url.pathname;
    calls.push({ method: req.method(), path, search: url.search, body: req.postData() });
    opts.onRequest?.(req, db);
    const fail = opts.fail ?? {};
    const cors = { "access-control-allow-origin": "*", "access-control-allow-headers": "*", "access-control-allow-methods": "*", "content-type": "application/json" };
    if (req.method() === "OPTIONS") return route.fulfill({ status: 204, headers: cors });
    if (path.startsWith("/auth/v1/user")) return route.fulfill({ status: 200, headers: cors, body: JSON.stringify({ id: OWNER.id, email: OWNER.email }) });
    if (path.startsWith("/auth/v1/token")) {
      if (fail["auth:refresh"]) return route.fulfill({ status: fail["auth:refresh"], headers: cors, body: JSON.stringify({ error: "invalid_grant", error_description: "Refresh Token Not Found" }) });
      return route.fulfill({ status: 200, headers: cors, body: JSON.stringify({ access_token: "test-access-2", refresh_token: "test-refresh-2", token_type: "bearer", expires_in: 3600, expires_at: Math.floor(Date.now() / 1000) + 3600, user: { id: OWNER.id, email: OWNER.email } }) });
    }
    if (path.startsWith("/auth/v1/logout")) return route.fulfill({ status: 204, headers: cors });
    const rpc = path.match(/^\/rest\/v1\/rpc\/(.+)$/);
    if (rpc) {
      const status = fail[`rpc:${rpc[1]}`];
      if (status) return route.fulfill({ status, headers: cors, body: JSON.stringify({ message: "simulated failure" }) });
      const out = rpc[1] === "claim_ownership" ? (opts.owner === false ? false : true) : null;
      return route.fulfill({ status: 200, headers: cors, body: JSON.stringify(out) });
    }
    const table = path.match(/^\/rest\/v1\/([a-z_]+)/)?.[1];
    if (table) {
      if (opts.slow?.[table]) await sleep(opts.slow[table]);
      const failing = fail[table] ?? fail["*"];
      if (failing) return route.fulfill({ status: failing, headers: cors, body: JSON.stringify({ message: `simulated ${table} failure`, code: "500" }) });
      if (req.method() === "GET" || req.method() === "HEAD") {
        if (table === "settings") {
          const key = (url.searchParams.get("key") || "").replace(/^eq\./, "");
          const rows = key in db.settings ? [{ value: db.settings[key] }] : [];
          return route.fulfill({ status: 200, headers: cors, body: JSON.stringify(rows) });
        }
        const rows = answer(db, table, url);
        return route.fulfill({ status: 200, headers: { ...cors, "content-range": `0-${Math.max(rows.length - 1, 0)}/${rows.length}` }, body: req.method() === "HEAD" ? "" : JSON.stringify(rows) });
      }
      // writes: remember them (settings upserts change the simulated database; inserted rows are kept)
      const body = JSON.parse(req.postData() || "{}");
      const rows = Array.isArray(body) ? body : [body];
      if (table === "settings") for (const r of rows) { if (r.key) db.settings[r.key] = r.value; }
      else if (req.method() === "POST") for (const r of rows) (db[table] ??= []).push({ id: `new-${Math.random().toString(16).slice(2)}`, created_at: new Date().toISOString(), ...r });
      return route.fulfill({ status: 201, headers: cors, body: "[]" });
    }
    return route.fulfill({ status: 404, headers: cors, body: "{}" });
  });
  await context.route(`${WORKER}/**`, async (route) => {
    const req = route.request();
    const url = new URL(req.url());
    calls.push({ method: req.method(), path: `worker:${url.pathname}`, body: req.postData() });
    const cors = { "access-control-allow-origin": "*", "access-control-allow-headers": "*", "content-type": "application/json" };
    if (req.method() === "OPTIONS") return route.fulfill({ status: 204, headers: cors });
    const status = (opts.fail ?? {})[`worker:${url.pathname}`] ?? (opts.fail ?? {})["worker:*"];
    if (status) return route.fulfill({ status, headers: cors, body: JSON.stringify({ error: "simulated Worker failure" }) });
    return route.fulfill({ status: 200, headers: cors, body: JSON.stringify({ ok: true }) });
  });
  const page = await context.newPage();
  const errors = [];
  page.on("pageerror", (e) => errors.push(String(e)));
  await page.goto(`${BASE}${path}`);
  return { page, context, calls, errors, db };
}

/** Another tab in the same browser (shares this device's storage). */
export async function newTab(context, path) {
  const page = await context.newPage();
  await page.goto(`${BASE}${path}`);
  return page;
}

export async function withBrowser(fn) {
  const browser = await chromium.launch();
  try { return await fn(browser); } finally { await browser.close(); }
}
