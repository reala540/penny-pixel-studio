// Setup wizard (owner only). Values pasted on the dashboard Setup page are encrypted here (AES-256-GCM, the same
// format as social logins) and stored in app_secrets, which no browser role can read. The Worker and the engine
// both load them at start-up and a saved value wins over the GitHub secret of the same name, so GitHub secrets
// keep working and nothing has to be entered twice. Responses only ever include a hint like "••••3f9a".

import { decryptJson, encryptJson, randomToken } from "./crypto";
import { Env, Supabase } from "./supabase";

export const MANAGED = [
  "TELEGRAM_BOT_TOKEN", "TELEGRAM_WEBHOOK_SECRET",
  "GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "FACEBOOK_APP_ID", "FACEBOOK_APP_SECRET",
  "TIKTOK_CLIENT_KEY", "TIKTOK_CLIENT_SECRET", "X_CLIENT_ID", "X_CLIENT_SECRET",
  "YOUTUBE_API_KEY", "PEXELS_API_KEY", "PIXABAY_API_KEY", "FRED_API_KEY", "SEC_USER_AGENT", "FREESOUND_API_KEY",
] as const;
export type ManagedName = (typeof MANAGED)[number];

/** Values the Worker itself reads (the rest are only used by the engine). */
const WORKER_READS = new Set<string>(["TELEGRAM_BOT_TOKEN", "TELEGRAM_WEBHOOK_SECRET", "GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET",
  "FACEBOOK_APP_ID", "FACEBOOK_APP_SECRET", "TIKTOK_CLIENT_KEY", "TIKTOK_CLIENT_SECRET", "X_CLIENT_ID", "X_CLIENT_SECRET"]);

/** Must stay in GitHub: the studio needs them before it can reach its own database. */
export const CORE = ["SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY", "SUPABASE_ANON_KEY", "SUPABASE_DB_URL", "TOKEN_ENCRYPTION_KEY",
  "CLOUDFLARE_API_TOKEN", "CLOUDFLARE_ACCOUNT_ID", "WORKER_GITHUB_TOKEN", "DASHBOARD_URL (variable)"];

export class SetupError extends Error {}

export type TestResult = { ok: boolean | null; detail: string };

type Row = { name: string; ciphertext: string; hint: string | null; updated_at: string };

let cache: { at: number; rows: Row[] } | null = null;
const TTL_MS = 60_000;

export function clearSecretCache(): void {
  cache = null;
}

async function savedRows(env: Env): Promise<Row[]> {
  if (cache && Date.now() - cache.at < TTL_MS) return cache.rows;
  const rows = await new Supabase(env).select<Row>("app_secrets", "select=name,ciphertext,hint,updated_at");
  cache = { at: Date.now(), rows };
  return rows;
}

/** The Worker's settings with dashboard-saved values on top. Never fails: on any problem the GitHub values stay. */
export async function withSavedSecrets(env: Env): Promise<Env> {
  let rows: Row[];
  try {
    rows = await savedRows(env);
  } catch {
    return env;  // database not migrated yet, or unreachable
  }
  const out: Record<string, unknown> = { ...env };
  for (const r of rows) {
    if (!(MANAGED as readonly string[]).includes(r.name)) continue;
    try {
      const v = (await decryptJson<{ value?: string }>(env.TOKEN_ENCRYPTION_KEY, r.ciphertext)).value;
      if (v) out[r.name] = v;
    } catch {
      // wrong key or damaged value: keep the GitHub value; the Setup page shows it as unreadable
    }
  }
  return out as unknown as Env;
}

export function hint(value: string): string {
  return value.length >= 8 ? `••••${value.slice(-4)}` : "••••";
}

function clean(name: string, raw: unknown): string {
  const v = typeof raw === "string" ? raw.trim() : "";
  if (!v) throw new SetupError("Paste a value first.");
  if (v.length > 1024 || /[\r\n]/.test(v)) throw new SetupError("That value is too long or has line breaks. Copy it again.");
  if (name === "SEC_USER_AGENT") {
    if (!/^[^@\s][^@]*\s+\S+@\S+\.\S+$/.test(v)) throw new SetupError("Use your name and email, like: Jane Doe jane@example.com");
    return v;
  }
  if (/\s/.test(v)) throw new SetupError("That value has spaces in it. Copy it again without spaces.");
  if (name === "TELEGRAM_BOT_TOKEN" && !/^\d{5,}:[A-Za-z0-9_-]{20,}$/.test(v)) {
    throw new SetupError("A bot token looks like 123456789:AA… — copy the whole line from @BotFather.");
  }
  if (name === "TELEGRAM_WEBHOOK_SECRET" && !/^[A-Za-z0-9_-]{8,256}$/.test(v)) {
    throw new SetupError("Use 8 or more letters, numbers, _ or - only.");
  }
  if (name === "GOOGLE_CLIENT_ID" && !v.endsWith(".apps.googleusercontent.com")) {
    throw new SetupError("A Google client ID ends with .apps.googleusercontent.com");
  }
  if (name === "FACEBOOK_APP_ID" && !/^\d{6,20}$/.test(v)) throw new SetupError("A Facebook App ID is a number (6–20 digits).");
  if (v.length < 6) throw new SetupError("That looks too short. Copy the whole value.");
  return v;
}

export function isManaged(name: unknown): name is ManagedName {
  return typeof name === "string" && (MANAGED as readonly string[]).includes(name);
}

async function getJson(url: string, init?: RequestInit): Promise<{ status: number; body: any }> {
  const r = await fetch(url, init);
  return { status: r.status, body: await r.json().catch(() => ({})) };
}

function form(data: Record<string, string>): RequestInit {
  return { method: "POST", headers: { "Content-Type": "application/x-www-form-urlencoded" }, body: new URLSearchParams(data).toString() };
}

/** Check a value (or pair) against the real service. ok=null means it can only be confirmed by connecting. */
export async function testValue(env: Env, name: ManagedName, origin: string): Promise<TestResult> {
  const e = env as unknown as Record<string, string | undefined>;
  const need = (...names: string[]) => names.find((n) => !e[n]);
  try {
    switch (name) {
      case "TELEGRAM_BOT_TOKEN": {
        const r = await getJson(`https://api.telegram.org/bot${e.TELEGRAM_BOT_TOKEN}/getMe`);
        return r.body?.ok ? { ok: true, detail: `Bot @${r.body.result?.username} is ready.` }
          : { ok: false, detail: "Telegram didn't accept this token. Copy it again from @BotFather." };
      }
      case "TELEGRAM_WEBHOOK_SECRET":
        return { ok: true, detail: "Saved. It protects the bot's link to the studio." };
      case "GOOGLE_CLIENT_ID":
      case "GOOGLE_CLIENT_SECRET": {
        const missing = need("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET");
        if (missing) return { ok: null, detail: `Add ${missing} too, then it can be checked.` };
        const r = await getJson("https://oauth2.googleapis.com/token", form({ client_id: e.GOOGLE_CLIENT_ID!, client_secret: e.GOOGLE_CLIENT_SECRET!,
          code: "studio-setup-check", grant_type: "authorization_code", redirect_uri: `${origin}/oauth/youtube/callback` }));
        if (r.body?.error === "invalid_client") return { ok: false, detail: "Google rejected this client ID and secret pair. Copy both again from Google Cloud → Credentials." };
        if (r.body?.error === "invalid_grant") return { ok: true, detail: "Google accepted the client ID and secret. Now press Connect for each YouTube channel." };
        return { ok: null, detail: `Google answered: ${r.body?.error_description ?? r.body?.error ?? `HTTP ${r.status}`}. Try connecting a channel.` };
      }
      case "FACEBOOK_APP_ID":
      case "FACEBOOK_APP_SECRET": {
        const missing = need("FACEBOOK_APP_ID", "FACEBOOK_APP_SECRET");
        if (missing) return { ok: null, detail: `Add ${missing} too, then it can be checked.` };
        const r = await getJson(`https://graph.facebook.com/oauth/access_token?${new URLSearchParams({ client_id: e.FACEBOOK_APP_ID!,
          client_secret: e.FACEBOOK_APP_SECRET!, grant_type: "client_credentials" })}`);
        return r.body?.access_token ? { ok: true, detail: "Facebook accepted the App ID and secret. Now press Connect for your Page." }
          : { ok: false, detail: `Facebook rejected them: ${r.body?.error?.message ?? `HTTP ${r.status}`}` };
      }
      case "TIKTOK_CLIENT_KEY":
      case "TIKTOK_CLIENT_SECRET": {
        const missing = need("TIKTOK_CLIENT_KEY", "TIKTOK_CLIENT_SECRET");
        if (missing) return { ok: null, detail: `Add ${missing} too, then it can be checked.` };
        const r = await getJson("https://open.tiktokapis.com/v2/oauth/token/", form({ client_key: e.TIKTOK_CLIENT_KEY!,
          client_secret: e.TIKTOK_CLIENT_SECRET!, grant_type: "client_credentials" }));
        return r.body?.access_token ? { ok: true, detail: "TikTok accepted the client key and secret. Now press Connect for TikTok." }
          : { ok: false, detail: `TikTok rejected them: ${r.body?.error_description ?? r.body?.error ?? `HTTP ${r.status}`}` };
      }
      case "X_CLIENT_ID":
      case "X_CLIENT_SECRET": {
        const missing = need("X_CLIENT_ID", "X_CLIENT_SECRET");
        if (missing) return { ok: null, detail: `Add ${missing} too, then it can be checked.` };
        const r = await getJson("https://api.x.com/2/oauth2/token", {
          ...form({ grant_type: "authorization_code", code: "studio-setup-check", code_verifier: "studio-setup-check",
            redirect_uri: `${origin}/oauth/x/callback` }),
          headers: { "Content-Type": "application/x-www-form-urlencoded", Authorization: `Basic ${btoa(`${e.X_CLIENT_ID}:${e.X_CLIENT_SECRET}`)}` },
        });
        if (r.status === 401 || r.body?.error === "unauthorized_client" || r.body?.error === "invalid_client") {
          return { ok: false, detail: "X rejected this client ID and secret. Copy both again from the X developer portal (OAuth 2.0 keys)." };
        }
        return { ok: null, detail: "Saved. X confirms these only when you press Connect for X." };
      }
      case "YOUTUBE_API_KEY": {
        const r = await getJson(`https://www.googleapis.com/youtube/v3/videoCategories?part=snippet&regionCode=US&key=${encodeURIComponent(e.YOUTUBE_API_KEY!)}`);
        return r.status === 200 ? { ok: true, detail: "YouTube accepted the key. Research can read YouTube trends." }
          : { ok: false, detail: `YouTube rejected the key: ${r.body?.error?.message ?? `HTTP ${r.status}`}. Check that YouTube Data API v3 is enabled.` };
      }
      case "PEXELS_API_KEY": {
        const r = await getJson("https://api.pexels.com/v1/search?query=city&per_page=1", { headers: { Authorization: e.PEXELS_API_KEY! } });
        return r.status === 200 ? { ok: true, detail: "Pexels accepted the key." } : { ok: false, detail: `Pexels rejected the key (HTTP ${r.status}).` };
      }
      case "FREESOUND_API_KEY": {
        const r = await getJson(`https://freesound.org/apiv2/search/text/?query=coin&page_size=1&token=${encodeURIComponent(e.FREESOUND_API_KEY!)}`);
        return r.status === 200 ? { ok: true, detail: "Freesound accepted the key. Animated scenes can use free sound effects." }
          : { ok: false, detail: `Freesound rejected the key (HTTP ${r.status}).` };
      }
      case "PIXABAY_API_KEY": {
        const r = await getJson(`https://pixabay.com/api/?key=${encodeURIComponent(e.PIXABAY_API_KEY!)}&q=city&per_page=3`);
        return r.status === 200 ? { ok: true, detail: "Pixabay accepted the key." } : { ok: false, detail: `Pixabay rejected the key (HTTP ${r.status}).` };
      }
      case "FRED_API_KEY": {
        const r = await getJson(`https://api.stlouisfed.org/fred/series?series_id=GNPCA&file_type=json&api_key=${encodeURIComponent(e.FRED_API_KEY!)}`);
        return r.status === 200 ? { ok: true, detail: "FRED accepted the key." } : { ok: false, detail: `FRED rejected the key: ${r.body?.error_message ?? `HTTP ${r.status}`}` };
      }
      case "SEC_USER_AGENT":
        return { ok: true, detail: "Saved. SEC asks for a name and email on every request." };
    }
  } catch (err) {
    return { ok: null, detail: `Couldn't reach the service to check (${(err as Error).message}). It's saved; try Test again later.` };
  }
}

export async function saveValue(env: Env, name: unknown, raw: unknown): Promise<{ hint: string; value: string }> {
  if (!isManaged(name)) throw new SetupError("Unknown setting.");
  const value = clean(name, raw);
  const db = new Supabase(env);
  await db.upsert("app_secrets", {
    name, ciphertext: await encryptJson(env.TOKEN_ENCRYPTION_KEY, { value }), hint: hint(value), updated_at: new Date().toISOString(),
  }, "name");
  clearSecretCache();
  await db.audit("setup_value_saved", { name, hint: hint(value) }, "owner");
  return { hint: hint(value), value };  // the value is for the caller's use only; never send it back to a browser
}

export async function removeValue(env: Env, name: unknown): Promise<void> {
  if (!isManaged(name)) throw new SetupError("Unknown setting.");
  const db = new Supabase(env);
  await db.remove("app_secrets", `name=eq.${encodeURIComponent(name)}`);
  clearSecretCache();
  await db.audit("setup_value_removed", { name }, "owner");
}

/** A Telegram webhook secret the owner never has to see: made once, saved like any other value. */
export async function ensureWebhookSecret(env: Env): Promise<Env> {
  if ((env.TELEGRAM_WEBHOOK_SECRET ?? "").trim()) return env;
  const secret = randomToken(24).replace(/[^A-Za-z0-9_-]/g, "");
  await saveValue(env, "TELEGRAM_WEBHOOK_SECRET", secret);
  return { ...env, TELEGRAM_WEBHOOK_SECRET: secret };
}

type Check = { ok: boolean; detail: string };

/** Everything the Setup page needs to show ✅/❌, without ever returning a secret. */
export async function setupStatus(raw: Env, env: Env): Promise<Record<string, unknown>> {
  const db = new Supabase(env);
  const core: Record<string, Check> = {};
  try {
    await db.select("settings", "select=key&limit=1");
    core.database = { ok: true, detail: "The Worker can reach your database." };
  } catch (e) {
    core.database = { ok: false, detail: `The Worker can't reach the database: ${(e as Error).message.slice(0, 120)}` };
  }
  try {
    const blob = await encryptJson(env.TOKEN_ENCRYPTION_KEY, { value: "check" });
    core.encryption = { ok: (await decryptJson<{ value: string }>(env.TOKEN_ENCRYPTION_KEY, blob)).value === "check", detail: "Encryption key works." };
  } catch {
    core.encryption = { ok: false, detail: "TOKEN_ENCRYPTION_KEY is missing or not 32 bytes. Fix the GitHub secret and run Deploy Worker." };
  }
  core.dashboard = env.DASHBOARD_URL ? { ok: true, detail: env.DASHBOARD_URL } : { ok: false, detail: "DASHBOARD_URL variable is missing in GitHub." };
  if (!env.GITHUB_TOKEN || !env.GITHUB_REPO) {
    core.github = { ok: false, detail: "WORKER_GITHUB_TOKEN is missing, so buttons can't start the engine. Add it in GitHub and run Deploy Worker." };
  } else {
    try {
      const r = await fetch(`https://api.github.com/repos/${env.GITHUB_REPO}/actions/workflows`, {
        headers: { Authorization: `Bearer ${env.GITHUB_TOKEN}`, Accept: "application/vnd.github+json", "User-Agent": "penny-pixel-studio" },
      });
      core.github = r.ok ? { ok: true, detail: `Can start the engine in ${env.GITHUB_REPO}.` }
        : { ok: false, detail: `GitHub refused the token (HTTP ${r.status}). It needs Actions: read and write on ${env.GITHUB_REPO}.` };
    } catch (e) {
      core.github = { ok: false, detail: `Couldn't reach GitHub: ${(e as Error).message}` };
    }
  }
  let rows: Row[] = [];
  try {
    rows = await savedRows(env);
  } catch {
    rows = [];
  }
  const presence = ((await db.setting<{ names?: Record<string, boolean>; checked_at?: string }>("engine_env_presence").catch(() => null)) ?? {});
  const rawEnv = raw as unknown as Record<string, string | undefined>;
  const values: Record<string, unknown> = {};
  for (const name of MANAGED) {
    const row = rows.find((r) => r.name === name);
    let readable = true;
    if (row) {
      try {
        await decryptJson(env.TOKEN_ENCRYPTION_KEY, row.ciphertext);
      } catch {
        readable = false;
      }
    }
    const inWorker = WORKER_READS.has(name) ? Boolean((rawEnv[name] ?? "").trim()) : null;
    const inEngine = presence.names ? Boolean(presence.names[name]) : null;
    values[name] = {
      dashboard: Boolean(row), hint: row?.hint ?? null, updated_at: row?.updated_at ?? null, readable,
      github: inWorker === true || inEngine === true ? true : inWorker === null && inEngine === null ? null : false,
    };
  }
  return { core, values, core_names: CORE, engine_checked_at: presence.checked_at ?? null };
}
