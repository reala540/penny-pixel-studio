// Penny & Pixel Studio — Cloudflare Worker (free plan; light work only, 10 ms CPU per request).
//   /api/dispatch      owner-only: start a GitHub Actions workflow (queue, research, produce, publish)
//   /api/oauth/start   owner-only: returns the platform sign-in URL
//   /oauth/:p/callback platform redirects here; tokens are encrypted and stored
//   /telegram/webhook  Telegram bot commands (verified secret header, linked owner chat only)
//   cron (15 min)      dispatches GitHub only when a post is due or a job is queued

import { randomToken, timingSafeEqual } from "./crypto";
import { addCredential, addProvider, deleteCredential, InputError, replaceCredential, testCredential } from "./credentials";
import { handleCallback, startUrl } from "./oauth";
import { Env, Supabase } from "./supabase";

const WORKFLOWS: Record<string, string> = {
  queue: "queue.yml",
  research: "weekly-research.yml",
  produce: "weekly-produce.yml",
  publish: "publish.yml",
};

function cors(env: Env): Record<string, string> {
  return {
    "Access-Control-Allow-Origin": env.DASHBOARD_URL || "*",
    "Access-Control-Allow-Headers": "authorization, content-type",
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
    Vary: "Origin",
  };
}

function json(env: Env, data: unknown, status = 200): Response {
  return new Response(JSON.stringify(data), { status, headers: { "Content-Type": "application/json", ...cors(env) } });
}

export async function dispatch(env: Env, workflow: keyof typeof WORKFLOWS | string, inputs: Record<string, string> = {}): Promise<boolean> {
  const file = WORKFLOWS[workflow];
  if (!file || !env.GITHUB_REPO || !env.GITHUB_TOKEN) return false;
  const r = await fetch(`https://api.github.com/repos/${env.GITHUB_REPO}/actions/workflows/${file}/dispatches`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${env.GITHUB_TOKEN}`,
      Accept: "application/vnd.github+json",
      "User-Agent": "penny-pixel-studio",
      "X-GitHub-Api-Version": "2022-11-28",
    },
    body: JSON.stringify({ ref: env.GITHUB_REF || "main", inputs }),
  });
  return r.status === 204;
}

async function telegram(env: Env, chatId: string | number, text: string): Promise<void> {
  if (!env.TELEGRAM_BOT_TOKEN) return;
  await fetch(`https://api.telegram.org/bot${env.TELEGRAM_BOT_TOKEN}/sendMessage`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ chat_id: chatId, text: text.slice(0, 4000), parse_mode: "HTML", disable_web_page_preview: true }),
  });
}

const HELP = [
  "<b>Penny &amp; Pixel Studio</b>",
  "/status – production health",
  "/week – this week's posting plan",
  "/review – items waiting for you",
  "/failed – recent problems",
  "/budget – X spending this month",
  "/pause – stop all publishing now",
  "/resume confirm – start publishing again",
  "/autopost – Auto Review &amp; Post status",
  "/autopost on confirm – let the AI approve packages that pass every check",
  "/autopost off – every package waits for your approval",
].join("\n");

type AutoPostResult = { on: boolean; was: boolean; reverted_posts: number };

/** One code path for the dashboard and Telegram: audited database switch, Telegram notice, review kick-off. */
export async function setAutoPost(env: Env, on: boolean, actor: "owner" | "telegram"): Promise<AutoPostResult & { notified: boolean; review_queued: boolean }> {
  const db = new Supabase(env);
  const result = await db.rpc<AutoPostResult>("set_auto_review_post", { p_on: on, p_actor: actor });
  // The switch is already saved and audited. Everything below is best effort: a Telegram or GitHub outage must
  // never make the dashboard report the wrong mode.
  let notified = false;
  let reviewQueued = false;
  try {
    const chat = await db.setting<string>("telegram_chat_id");
    if (chat) {
      const where = actor === "telegram" ? "from Telegram" : "from the dashboard";
      await telegram(env, chat, on
        ? `🤖 <b>Auto Review &amp; Post: ON</b> (${where}).\nPackages that pass every check are approved and posted at their scheduled times. Anything else comes to you here. Send /autopost off to stop.`
        : `🧑 <b>Auto Review &amp; Post: OFF</b> (${where}).\nEvery package waits for your approval.${result.reverted_posts ? ` ${result.reverted_posts} auto-approved post(s) that hadn't gone out are back in Review.` : ""}`);
      notified = true;
    }
  } catch (e) {
    console.error("autopost notice", (e as Error).message);
  }
  if (on) {
    try {
      // review what's already waiting, once (unique key per switch-on)
      await db.insertReturning("generation_jobs", { job_type: "auto_review", idempotency_key: `auto_review:${Date.now()}`,
        status: "queued", requested_by: "owner", input: { trigger: actor } }, { onConflict: "idempotency_key", ignoreDuplicates: true });
      reviewQueued = true;
      await dispatch(env, "queue");
    } catch (e) {
      console.error("autopost review kick-off", (e as Error).message);  // the 15-minute check picks the job up anyway
    }
  }
  return { ...result, notified, review_queued: reviewQueued };
}

export async function autoPostStatus(db: Supabase): Promise<string> {
  const on = (await db.setting<boolean>("auto_review_post")) === true;
  return `Auto Review &amp; Post: <b>${on ? "ON" : "OFF"}</b>`;
}

function esc(s: string): string {
  return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

/** The webhook secret without stray whitespace from copy-paste. */
const hookSecret = (env: Env) => (env.TELEGRAM_WEBHOOK_SECRET ?? "").trim();

/** Point the bot at this Worker (idempotent) and explain any problem in plain words. */
export async function connectTelegram(env: Env, hookUrl: string): Promise<{ ok: boolean; problem?: string }> {
  if (!env.TELEGRAM_BOT_TOKEN) return { ok: false, problem: "TELEGRAM_BOT_TOKEN is not set. Add it as a GitHub secret and run Deploy Worker again." };
  const secret = hookSecret(env);
  if (!secret) return { ok: false, problem: "TELEGRAM_WEBHOOK_SECRET is not set. Add it as a GitHub secret and run Deploy Worker again." };
  if (!/^[A-Za-z0-9_-]{1,256}$/.test(secret)) {
    return { ok: false, problem: "TELEGRAM_WEBHOOK_SECRET may only use letters, numbers, _ and -. Change the GitHub secret and run Deploy Worker again." };
  }
  try {
    const r = await fetch(`https://api.telegram.org/bot${env.TELEGRAM_BOT_TOKEN}/setWebhook`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url: hookUrl, secret_token: secret, allowed_updates: ["message"] }),
    });
    const body = (await r.json().catch(() => ({}))) as { ok?: boolean; description?: string };
    if (body.ok) return { ok: true };
    if (r.status === 401 || r.status === 404) {
      return { ok: false, problem: "Telegram rejected TELEGRAM_BOT_TOKEN. Copy the token from @BotFather again, update the GitHub secret and run Deploy Worker again." };
    }
    return { ok: false, problem: `Telegram said: ${body.description ?? `HTTP ${r.status}`}` };
  } catch (e) {
    return { ok: false, problem: `Couldn't reach Telegram: ${(e as Error).message}` };
  }
}

export async function handleTelegram(env: Env, req: Request): Promise<Response> {
  const secret = req.headers.get("X-Telegram-Bot-Api-Secret-Token") ?? "";
  if (!hookSecret(env) || !timingSafeEqual(secret, hookSecret(env))) {
    return new Response("forbidden", { status: 403 });
  }
  const update = (await req.json().catch(() => ({}))) as any;
  const msg = update.message;
  if (!msg?.text || !msg.chat?.id) return new Response("ok");
  const chatId = String(msg.chat.id);
  try {
    return await handleCommand(env, msg, chatId);
  } catch (e) {
    // Always answer 200: an error response makes Telegram resend the same message and hold back newer ones.
    console.error("telegram command failed", e);
    await telegram(env, chatId, "Sorry, something went wrong on the studio side. Please try again in a minute.").catch(() => {});
    return new Response("ok");
  }
}

async function handleCommand(env: Env, msg: any, chatId: string): Promise<Response> {
  const db = new Supabase(env);
  const linked = await db.setting<string>("telegram_chat_id");
  const [cmd, ...args] = msg.text.trim().split(/\s+/);
  const dash = env.DASHBOARD_URL.replace(/\/$/, "");

  if (cmd === "/link") {
    const code = await db.setting<string>("telegram_link_code");
    if (code && args[0] && timingSafeEqual(args[0], code)) {
      await db.putSetting("telegram_chat_id", chatId);
      await db.deleteSetting("telegram_link_code");
      await db.audit("telegram_linked", { chat: chatId });
      await telegram(env, chatId, "Linked! You'll get studio updates here.\n\n" + HELP);
    } else {
      await telegram(env, chatId, "That code didn't match. Get a fresh code in Dashboard → Settings → Telegram.");
    }
    return new Response("ok");
  }
  if (!linked || linked !== chatId) {
    await telegram(env, chatId, "This bot is private. Link it from Dashboard → Settings → Telegram.");
    return new Response("ok");
  }

  switch (cmd) {
    case "/start":
    case "/help":
      await telegram(env, chatId, HELP);
      break;
    case "/status": {
      const projects = await db.select<{ status: string }>("content_projects", "select=status&order=created_at.desc&limit=200");
      const posts = await db.select<{ status: string }>("scheduled_posts", "select=status&order=scheduled_at.desc&limit=200");
      const count = (rows: { status: string }[]) =>
        Object.entries(rows.reduce<Record<string, number>>((a, r) => ((a[r.status] = (a[r.status] ?? 0) + 1), a), {}))
          .map(([k, v]) => `${k.replace(/_/g, " ")}: ${v}`)
          .join("\n") || "nothing yet";
      const paused = await db.setting<boolean>("paused");
      await telegram(env, chatId, `<b>Status</b>${paused ? " (PAUSED)" : ""}\n${await autoPostStatus(db)}\n\n<b>Videos</b>\n${count(projects)}\n\n<b>Posts</b>\n${count(posts)}`);
      break;
    }
    case "/week": {
      const now = new Date();
      const end = new Date(now.getTime() + 7 * 86400_000);
      const rows = await db.select<any>(
        "scheduled_posts",
        `select=scheduled_at,status,content_variants(title,kind),social_accounts(label)&scheduled_at=gte.${now.toISOString()}&scheduled_at=lte.${end.toISOString()}&order=scheduled_at.asc&limit=40`,
      );
      const tz = (await db.setting<string>("timezone")) ?? "Africa/Nairobi";
      const lines = rows.map((r) => {
        const when = new Date(r.scheduled_at).toLocaleString("en-GB", { timeZone: tz, weekday: "short", hour: "2-digit", minute: "2-digit" });
        return `${when} · ${esc(r.social_accounts?.label ?? "")} · ${esc(r.content_variants?.title ?? r.content_variants?.kind ?? "")} (${r.status.replace(/_/g, " ")})`;
      });
      await telegram(env, chatId, `<b>Next 7 days</b>\n${lines.join("\n") || "Nothing scheduled."}\n\n<a href="${dash}/calendar">Open calendar</a>`);
      break;
    }
    case "/review": {
      const rows = await db.select<any>("content_projects", "select=title,status&status=in.(ready_for_review,needs_attention)&order=created_at.desc&limit=20");
      await telegram(env, chatId, `<b>Waiting for you: ${rows.length}</b>\n${rows.map((r) => `• ${esc(r.title)}${r.status === "needs_attention" ? " ⚠️" : ""}`).join("\n")}\n\n<a href="${dash}/review">Open Review Studio</a>`);
      break;
    }
    case "/failed": {
      const since = new Date(Date.now() - 7 * 86400_000).toISOString();
      const jobs = await db.select<any>("generation_jobs", `select=job_type,error_message&status=in.(failed,blocked)&created_at=gte.${since}&limit=10`);
      const posts = await db.select<any>("scheduled_posts", `select=last_error,status&status=in.(failed,blocked,needs_review,needs_manual)&updated_at=gte.${since}&limit=10`);
      const lines = [...jobs.map((j) => `• ${j.job_type}: ${esc(String(j.error_message ?? "").slice(0, 120))}`), ...posts.map((p) => `• post ${p.status.replace(/_/g, " ")}: ${esc(String(p.last_error ?? "").slice(0, 120))}`)];
      await telegram(env, chatId, `<b>Problems (7 days)</b>\n${lines.join("\n") || "None 🎉"}`);
      break;
    }
    case "/budget": {
      const month = new Date().toISOString().slice(0, 7) + "-01";
      const res = await db.select<any>("budget_reservations", `select=amount_usd,status&service=eq.x_api&month=eq.${month}`);
      const cap = (await db.select<any>("budgets", "select=monthly_cap_usd&service=eq.x_api"))[0]?.monthly_cap_usd ?? 1;
      const spent = res.filter((r) => r.status === "committed").reduce((a, r) => a + Number(r.amount_usd), 0);
      await telegram(env, chatId, `<b>X budget</b>\nSpent: $${spent.toFixed(3)} of $${Number(cap).toFixed(2)} this month.`);
      break;
    }
    case "/pause":
      await db.putSetting("paused", true);
      await db.audit("paused", { via: "telegram" }, "telegram");
      await telegram(env, chatId, "⏸ All publishing is paused. Send /resume confirm to start again.");
      break;
    case "/resume":
      if (args[0] !== "confirm") {
        await telegram(env, chatId, "To resume publishing, send: /resume confirm");
        break;
      }
      await db.putSetting("paused", false);
      await db.audit("resumed", { via: "telegram" }, "telegram");
      await telegram(env, chatId, "▶️ Publishing resumed.");
      break;
    case "/autopost": {
      const want = (args[0] ?? "").toLowerCase();
      if (want === "off") {
        await setAutoPost(env, false, "telegram");
      } else if (want === "on" && args[1] === "confirm") {
        await setAutoPost(env, true, "telegram");
      } else if (want === "on") {
        await telegram(env, chatId, "With Auto Review &amp; Post ON, the AI approves packages that pass every quality, fact, freshness, destination and policy check, and they post at their scheduled times without you. Anything else comes to you.\n\nTo switch it on, send: /autopost on confirm");
      } else {
        await telegram(env, chatId, `${await autoPostStatus(db)}\n\n/autopost on confirm – automatic\n/autopost off – manual approval`);
      }
      break;
    }
    default:
      await telegram(env, chatId, HELP);
  }
  return new Response("ok");
}

async function ownerOrNull(env: Env, req: Request): Promise<string | null> {
  const auth = req.headers.get("Authorization") ?? "";
  return new Supabase(env).ownerFromToken(auth.startsWith("Bearer ") ? auth.slice(7) : null);
}

export async function handleFetch(req: Request, env: Env): Promise<Response> {
  const url = new URL(req.url);
  if (req.method === "OPTIONS") return new Response(null, { headers: cors(env) });
  if (url.pathname === "/health") return json(env, { ok: true });

  if (url.pathname === "/api/dispatch" && req.method === "POST") {
    const owner = await ownerOrNull(env, req);
    if (!owner) return json(env, { error: "not authorised" }, 401);
    const body = (await req.json().catch(() => ({}))) as { workflow?: string };
    if (!body.workflow || !(body.workflow in WORKFLOWS)) return json(env, { error: "unknown workflow" }, 400);
    const ok = await dispatch(env, body.workflow);
    await new Supabase(env).audit("dispatch", { workflow: body.workflow, ok }, "owner");
    return json(env, { ok }, ok ? 200 : 502);
  }

  if (url.pathname === "/api/oauth/start" && req.method === "POST") {
    const owner = await ownerOrNull(env, req);
    if (!owner) return json(env, { error: "not authorised" }, 401);
    const body = (await req.json().catch(() => ({}))) as { account_id?: string };
    if (!body.account_id) return json(env, { error: "account_id required" }, 400);
    const acc = await new Supabase(env).select<{ id: string; platform: string }>("social_accounts", `id=eq.${encodeURIComponent(body.account_id)}&select=id,platform`);
    if (!acc.length) return json(env, { error: "unknown account" }, 404);
    return json(env, { url: await startUrl(env, req, acc[0].platform as any, acc[0].id) });
  }

  if (url.pathname === "/api/telegram/link-code" && req.method === "POST") {
    const owner = await ownerOrNull(env, req);
    if (!owner) return json(env, { error: "not authorised" }, 401);
    const code = randomToken(6).replace(/[^A-Za-z0-9]/g, "").slice(0, 8).toUpperCase();
    await new Supabase(env).putSetting("telegram_link_code", code);
    return json(env, { code, telegram: await connectTelegram(env, `${url.origin}/telegram/webhook`) });
  }

  if (url.pathname === "/api/autopost" && req.method === "POST") {
    const owner = await ownerOrNull(env, req);
    if (!owner) return json(env, { error: "not authorised" }, 401);
    const body = (await req.json().catch(() => ({}))) as { on?: unknown; confirm?: unknown };
    if (typeof body.on !== "boolean") return json(env, { error: "send {on: true|false}" }, 400);
    if (body.on && body.confirm !== true) return json(env, { error: "Switching ON needs confirm: true" }, 400);
    return json(env, await setAutoPost(env, body.on, "owner"));
  }

  const manager: Record<string, (env: Env, body: Record<string, unknown>) => Promise<Record<string, unknown>>> = {
    "/api/credentials/add": addCredential,
    "/api/credentials/replace": replaceCredential,
    "/api/credentials/delete": deleteCredential,
    "/api/credentials/test": testCredential,
    "/api/providers/add": addProvider,
  };
  if (url.pathname in manager && req.method === "POST") {
    const owner = await ownerOrNull(env, req);
    if (!owner) return json(env, { error: "not authorised" }, 401);
    const body = (await req.json().catch(() => null)) as Record<string, unknown> | null;
    if (!body || typeof body !== "object") return json(env, { error: "send a JSON object" }, 400);
    try {
      return json(env, await manager[url.pathname](env, body));
    } catch (e) {
      if (e instanceof InputError) return json(env, { error: e.message }, 400);
      console.error("api manager", url.pathname, (e as Error).message);
      return json(env, { error: "Something went wrong on the server; nothing was saved." }, 500);
    }
  }

  const cb = url.pathname.match(/^\/oauth\/(youtube|facebook|tiktok|x)\/callback$/);
  if (cb && req.method === "GET") return handleCallback(env, req, cb[1] as any);

  if (url.pathname === "/telegram/webhook" && req.method === "POST") return handleTelegram(env, req);

  return json(env, { error: "not found" }, 404);
}

/** Cron: only spend GitHub minutes when there is real work. */
export async function handleCron(env: Env): Promise<Record<string, boolean>> {
  const db = new Supabase(env);
  const out: Record<string, boolean> = {};
  const soon = new Date(Date.now() + 10 * 60_000).toISOString();
  const due = await db.select("scheduled_posts", `select=id&status=eq.scheduled&scheduled_at=lte.${soon}&limit=1`);
  const paused = await db.setting<boolean>("paused");
  const last = (await db.setting<string>("last_publish_dispatch")) ?? "1970-01-01T00:00:00Z";
  if (due.length && !paused && Date.now() - Date.parse(last) > 12 * 60_000) {
    out.publish = await dispatch(env, "publish");
    if (out.publish) await db.putSetting("last_publish_dispatch", new Date().toISOString());
  }
  if (await scheduleIdeas(db)) out.ideas = true;
  const queued = await db.select("generation_jobs", "select=id&status=eq.queued&requested_by=eq.owner&limit=1");
  const lastQ = (await db.setting<string>("last_queue_dispatch")) ?? "1970-01-01T00:00:00Z";
  if (queued.length && (out.ideas || Date.now() - Date.parse(lastQ) > 12 * 60_000)) {
    out.queue = await dispatch(env, "queue");
    if (out.queue) await db.putSetting("last_queue_dispatch", new Date().toISOString());
  }
  return out;
}

type IdeaSchedule = { frequency?: string; weekdays?: number[]; hour?: number };

/** Local calendar date, weekday (0 = Monday) and hour in the studio's timezone. */
export function localParts(now: Date, timeZone: string): { date: string; weekday: number; hour: number } {
  let tz = timeZone;
  try {
    new Intl.DateTimeFormat("en-GB", { timeZone: tz });
  } catch {
    tz = "UTC";
  }
  const parts = Object.fromEntries(new Intl.DateTimeFormat("en-GB", {
    timeZone: tz, year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", hourCycle: "h23", weekday: "short",
  }).formatToParts(now).map((p) => [p.type, p.value]));
  const weekday = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"].indexOf(parts.weekday);
  return { date: `${parts.year}-${parts.month}-${parts.day}`, weekday, hour: Number(parts.hour) };
}

/** The slot key due now for an idea schedule, or null. One job per slot, ever. */
export function dueIdeaSlot(cfg: IdeaSchedule | null, now: Date, timeZone: string): string | null {
  if (!cfg || !["daily", "weekly", "custom"].includes(cfg.frequency ?? "")) return null;
  const { date, weekday, hour } = localParts(now, timeZone);
  if (hour < Math.min(Math.max(Number(cfg.hour ?? 8), 0), 23)) return null;
  if (cfg.frequency !== "daily") {
    const days = (cfg.weekdays?.length ? cfg.weekdays : [0]).map(Number);
    if (!days.includes(weekday)) return null;
  }
  return `ideas:auto:${date}`;
}

async function scheduleIdeas(db: Supabase): Promise<boolean> {
  if (await db.setting<boolean>("paused_ideas")) return false;
  const slot = dueIdeaSlot(await db.setting<IdeaSchedule>("idea_generator"), new Date(),
    (await db.setting<string>("timezone")) ?? "Africa/Nairobi");
  if (!slot) return false;
  const made = await db.insertReturning("generation_jobs", {
    job_type: "generate_ideas", idempotency_key: slot, status: "queued", requested_by: "owner",
    input: { trigger: "scheduled" },
  }, { onConflict: "idempotency_key", ignoreDuplicates: true });
  return made.length > 0;
}

export default {
  fetch: (req: Request, env: Env) => handleFetch(req, env),
  scheduled: async (_event: ScheduledEvent, env: Env, ctx: ExecutionContext) => {
    ctx.waitUntil(handleCron(env));
  },
};
