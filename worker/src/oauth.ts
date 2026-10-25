// OAuth connect flows for YouTube (Google), Facebook Pages, TikTok and X.
// State is AES-GCM encrypted (carries account id, platform, expiry and the PKCE verifier),
// so no server-side session storage is needed.

import { decryptJson, encryptJson, pkceChallenge, randomToken } from "./crypto";
import { Env, Supabase } from "./supabase";

type Platform = "youtube" | "facebook" | "tiktok" | "x";

interface State {
  a: string; // social_account_id
  p: Platform;
  v: string; // PKCE verifier / nonce
  e: number; // expiry (ms)
}

const SCOPES: Record<Platform, string> = {
  // yt-analytics(-monetary).readonly: views, watch time, retention, click-through and revenue per video (read-only)
  youtube: "https://www.googleapis.com/auth/youtube.upload https://www.googleapis.com/auth/youtube.readonly https://www.googleapis.com/auth/yt-analytics.readonly https://www.googleapis.com/auth/yt-analytics-monetary.readonly",
  facebook: "pages_show_list,pages_read_engagement,pages_manage_posts,business_management",
  tiktok: "user.info.basic,video.upload,video.publish",
  x: "tweet.read tweet.write users.read offline.access",
};

export function callbackUrl(req: Request, platform: Platform): string {
  const u = new URL(req.url);
  return `${u.origin}/oauth/${platform}/callback`;
}

export async function startUrl(env: Env, req: Request, platform: Platform, accountId: string): Promise<string> {
  const verifier = randomToken(48);
  const state = await encryptJson(env.TOKEN_ENCRYPTION_KEY, { a: accountId, p: platform, v: verifier, e: Date.now() + 15 * 60_000 } satisfies State);
  const redirect = callbackUrl(req, platform);
  const s = encodeURIComponent(state);
  switch (platform) {
    case "youtube":
      return (
        "https://accounts.google.com/o/oauth2/v2/auth?" +
        new URLSearchParams({
          client_id: env.GOOGLE_CLIENT_ID ?? "",
          redirect_uri: redirect,
          response_type: "code",
          scope: SCOPES.youtube,
          access_type: "offline",
          prompt: "consent select_account",
          include_granted_scopes: "true",
        }) + `&state=${s}`
      );
    case "facebook":
      return (
        "https://www.facebook.com/v23.0/dialog/oauth?" +
        new URLSearchParams({ client_id: env.FACEBOOK_APP_ID ?? "", redirect_uri: redirect, scope: SCOPES.facebook, response_type: "code" }) +
        `&state=${s}`
      );
    case "tiktok":
      return (
        "https://www.tiktok.com/v2/auth/authorize/?" +
        new URLSearchParams({
          client_key: env.TIKTOK_CLIENT_KEY ?? "",
          redirect_uri: redirect,
          scope: SCOPES.tiktok,
          response_type: "code",
        }) + `&state=${s}`
      );
    case "x":
      return (
        "https://x.com/i/oauth2/authorize?" +
        new URLSearchParams({
          client_id: env.X_CLIENT_ID ?? "",
          redirect_uri: redirect,
          scope: SCOPES.x,
          response_type: "code",
          code_challenge: await pkceChallenge(verifier),
          code_challenge_method: "S256",
        }) + `&state=${s}`
      );
  }
}

async function form(url: string, body: Record<string, string>, headers: Record<string, string> = {}): Promise<any> {
  const r = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded", ...headers },
    body: new URLSearchParams(body),
  });
  const data = (await r.json().catch(() => ({}))) as any;
  if (!r.ok || data.error) throw new Error(`token exchange failed: ${data.error_description || data.error?.message || data.error || r.status}`);
  return data;
}

async function getJson(url: string, token?: string): Promise<any> {
  const r = await fetch(url, { headers: token ? { Authorization: `Bearer ${token}` } : {} });
  const data = (await r.json().catch(() => ({}))) as any;
  if (!r.ok) throw new Error(`${new URL(url).host}: ${r.status} ${JSON.stringify(data).slice(0, 200)}`);
  return data;
}

export async function handleCallback(env: Env, req: Request, platform: Platform): Promise<Response> {
  const url = new URL(req.url);
  const dash = env.DASHBOARD_URL.replace(/\/$/, "");
  const fail = (msg: string) => Response.redirect(`${dash}/settings?connect_error=${encodeURIComponent(msg)}`, 302);
  if (url.searchParams.get("error")) return fail(url.searchParams.get("error_description") || url.searchParams.get("error")!);
  const code = url.searchParams.get("code");
  const rawState = url.searchParams.get("state");
  if (!code || !rawState) return fail("missing code");
  let state: State;
  try {
    state = await decryptJson<State>(env.TOKEN_ENCRYPTION_KEY, rawState);
  } catch {
    return fail("invalid state");
  }
  if (state.p !== platform || state.e < Date.now()) return fail("expired or mismatched sign-in, please try again");
  const redirect = callbackUrl(req, platform);
  const now = Date.now() / 1000;
  let tokens: Record<string, unknown>;
  let externalId = "";
  let handle = "";
  let scopes: string[] = [];
  try {
    if (platform === "youtube") {
      const t = await form("https://oauth2.googleapis.com/token", {
        code, client_id: env.GOOGLE_CLIENT_ID ?? "", client_secret: env.GOOGLE_CLIENT_SECRET ?? "",
        redirect_uri: redirect, grant_type: "authorization_code",
      });
      if (!t.refresh_token) return fail("Google did not return a refresh token; remove the app's access in your Google account and try again");
      const ch = await getJson("https://www.googleapis.com/youtube/v3/channels?part=snippet&mine=true", t.access_token);
      const item = ch.items?.[0];
      if (!item) return fail("No YouTube channel on that Google account");
      externalId = item.id;
      handle = item.snippet?.customUrl ?? item.snippet?.title ?? "";
      scopes = String(t.scope ?? "").split(" ");
      tokens = { access_token: t.access_token, refresh_token: t.refresh_token, expires_at: now + Number(t.expires_in ?? 3600), channel_id: externalId };
    } else if (platform === "facebook") {
      const short = await getJson(
        "https://graph.facebook.com/v23.0/oauth/access_token?" +
          new URLSearchParams({ client_id: env.FACEBOOK_APP_ID ?? "", client_secret: env.FACEBOOK_APP_SECRET ?? "", redirect_uri: redirect, code }),
      );
      const long = await getJson(
        "https://graph.facebook.com/v23.0/oauth/access_token?" +
          new URLSearchParams({ grant_type: "fb_exchange_token", client_id: env.FACEBOOK_APP_ID ?? "", client_secret: env.FACEBOOK_APP_SECRET ?? "", fb_exchange_token: short.access_token }),
      );
      // Page tokens obtained from a long-lived user token do not expire.
      const pages = await getJson(`https://graph.facebook.com/v23.0/me/accounts?fields=id,name,access_token&access_token=${long.access_token}`);
      const page = pages.data?.[0];
      if (!page) return fail("No Facebook Page found. Create a Page first, then connect again.");
      externalId = page.id;
      handle = page.name;
      scopes = SCOPES.facebook.split(",");
      tokens = { page_id: page.id, page_token: page.access_token, page_name: page.name };
    } else if (platform === "tiktok") {
      const t = await form("https://open.tiktokapis.com/v2/oauth/token/", {
        client_key: env.TIKTOK_CLIENT_KEY ?? "", client_secret: env.TIKTOK_CLIENT_SECRET ?? "", code,
        grant_type: "authorization_code", redirect_uri: redirect,
      });
      externalId = t.open_id;
      scopes = String(t.scope ?? "").split(",");
      tokens = { access_token: t.access_token, refresh_token: t.refresh_token, expires_at: now + Number(t.expires_in ?? 86400), open_id: t.open_id };
    } else {
      const basic: Record<string, string> = env.X_CLIENT_SECRET ? { Authorization: `Basic ${btoa(`${env.X_CLIENT_ID}:${env.X_CLIENT_SECRET}`)}` } : {};
      const t = await form(
        "https://api.x.com/2/oauth2/token",
        { code, grant_type: "authorization_code", client_id: env.X_CLIENT_ID ?? "", redirect_uri: redirect, code_verifier: state.v },
        basic,
      );
      const me = await getJson("https://api.x.com/2/users/me", t.access_token);
      externalId = me.data?.id ?? "";
      handle = me.data?.username ? `@${me.data.username}` : "";
      scopes = String(t.scope ?? "").split(" ");
      tokens = { access_token: t.access_token, refresh_token: t.refresh_token, expires_at: now + Number(t.expires_in ?? 7200), user_id: externalId };
    }
  } catch (e) {
    return fail(String((e as Error).message).slice(0, 200));
  }
  const db = new Supabase(env);
  await db.upsert("oauth_secrets", { social_account_id: state.a, ciphertext: await encryptJson(env.TOKEN_ENCRYPTION_KEY, tokens), updated_at: new Date().toISOString() }, "social_account_id");
  await db.update("oauth_connections", `social_account_id=eq.${state.a}`, {
    status: "connected", scopes, last_error: null, connected_at: new Date().toISOString(), last_checked_at: new Date().toISOString(),
    token_expires_at: typeof tokens.expires_at === "number" ? new Date((tokens.expires_at as number) * 1000).toISOString() : null,
  });
  await db.update("social_accounts", `id=eq.${state.a}`, { external_id: externalId, handle });
  await db.audit("account_connected", { platform, account: state.a, handle });
  return Response.redirect(`${dash}/settings?connected=${platform}`, 302);
}
