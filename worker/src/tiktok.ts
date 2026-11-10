// TikTok Direct Post: the owner's posting screen on the dashboard (TikTok's Content Sharing Guidelines).
//   /api/tiktok/creator  owner-only: the connected creator's live settings (name, avatar, who-can-watch options,
//                        comment/Duet/Stitch switches the creator turned off, longest allowed video, whether they can post)
//   /api/tiktok/confirm  owner-only: saves one post's choices after checking them against those live settings
// Nothing here posts. The engine posts at the scheduled time using exactly the confirmed choices and checks them again.

import { decryptJson, encryptJson } from "./crypto";
import { Env, Supabase } from "./supabase";

export class TikTokError extends Error {}

export type Creator = {
  creator_avatar_url?: string; creator_username?: string; creator_nickname?: string;
  privacy_level_options: string[]; comment_disabled: boolean; duet_disabled: boolean; stitch_disabled: boolean;
  max_video_post_duration_sec?: number; can_post?: boolean;
};

export type Choices = {
  privacy_level?: string; allow_comment?: boolean; allow_duet?: boolean; allow_stitch?: boolean;
  disclose?: boolean; your_brand?: boolean; branded_content?: boolean; consent?: boolean;
};

/** Why these choices can't be saved, or null. Mirrors TikTok's rules: no default audience, branded content can't be
 * private, a disclosure must say what it is, switches the creator turned off stay off, and the owner must agree. */
export function choiceProblem(c: Choices, creator: Creator, seconds?: number | null): string | null {
  if (creator.can_post === false) return "TikTok says this account can't post right now (daily limit). Try again later.";
  if (!c.privacy_level) return "Choose who can watch this video.";
  if (!creator.privacy_level_options.includes(c.privacy_level)) return "That audience isn't available for this account.";
  if (c.disclose && !c.your_brand && !c.branded_content) return "You switched on commercial content: choose 'Your brand', 'Branded content' or both.";
  if (c.disclose && c.branded_content && c.privacy_level === "SELF_ONLY") return "Branded content can't be private. Choose another audience.";
  if ((c.allow_comment && creator.comment_disabled) || (c.allow_duet && creator.duet_disabled) || (c.allow_stitch && creator.stitch_disabled))
    return "A switch the account has turned off in TikTok can't be turned on here.";
  if (seconds && creator.max_video_post_duration_sec && seconds > creator.max_video_post_duration_sec)
    return `This video is ${Math.round(seconds)} seconds; this account can post at most ${creator.max_video_post_duration_sec}.`;
  if (!c.consent) return "Agree to TikTok's Music Usage Confirmation to post.";
  return null;
}

type Tokens = { access_token: string; refresh_token?: string; expires_at?: number; open_id?: string };

async function tiktokAccount(db: Supabase, accountId?: string): Promise<{ id: string }> {
  const q = accountId ? `id=eq.${encodeURIComponent(accountId)}&platform=eq.tiktok&select=id` : "platform=eq.tiktok&enabled=eq.true&select=id&limit=1";
  const rows = await db.select<{ id: string }>("social_accounts", q);
  if (!rows.length) throw new TikTokError("No TikTok account is set up.");
  return rows[0];
}

/** A working access token, refreshed (and saved) when it is about to expire. */
export async function accessToken(env: Env, accountId: string): Promise<string> {
  const db = new Supabase(env);
  const sec = await db.select<{ ciphertext: string }>("oauth_secrets", `social_account_id=eq.${encodeURIComponent(accountId)}&select=ciphertext`);
  if (!sec.length) throw new TikTokError("TikTok isn't connected. Connect it on the Setup page.");
  const t = await decryptJson<Tokens>(env.TOKEN_ENCRYPTION_KEY, sec[0].ciphertext);
  const now = Math.floor(Date.now() / 1000);
  if (t.access_token && (t.expires_at ?? 0) > now + 120) return t.access_token;
  if (!t.refresh_token) throw new TikTokError("The TikTok login has expired. Connect TikTok again on the Setup page.");
  const r = await fetch("https://open.tiktokapis.com/v2/oauth/token/", {
    method: "POST", headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({ client_key: env.TIKTOK_CLIENT_KEY ?? "", client_secret: env.TIKTOK_CLIENT_SECRET ?? "",
      grant_type: "refresh_token", refresh_token: t.refresh_token }),
  });
  const n = (await r.json().catch(() => ({}))) as any;
  if (!r.ok || !n.access_token) throw new TikTokError("The TikTok login has expired. Connect TikTok again on the Setup page.");
  const fresh: Tokens = { ...t, access_token: n.access_token, refresh_token: n.refresh_token ?? t.refresh_token, expires_at: now + Number(n.expires_in ?? 86400) };
  await db.update("oauth_secrets", `social_account_id=eq.${encodeURIComponent(accountId)}`,
    { ciphertext: await encryptJson(env.TOKEN_ENCRYPTION_KEY, fresh), updated_at: new Date().toISOString() });
  return fresh.access_token;
}

export async function creatorInfo(env: Env, accountId?: string): Promise<Creator & { account_id: string; direct_post: boolean }> {
  const db = new Supabase(env);
  const acc = await tiktokAccount(db, accountId);
  const conn = await db.select<{ scopes: string[] | null }>("oauth_connections", `social_account_id=eq.${acc.id}&select=scopes`);
  const direct = (conn[0]?.scopes ?? []).includes("video.publish");
  const token = await accessToken(env, acc.id);
  const r = await fetch("https://open.tiktokapis.com/v2/post/publish/creator_info/query/", {
    method: "POST", headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json; charset=UTF-8" },
  });
  const body = (await r.json().catch(() => ({}))) as any;
  const code = body?.error?.code;
  if (!r.ok || (code && code !== "ok")) {
    if (code === "scope_not_authorized") throw new TikTokError("TikTok Direct Post isn't allowed for this connection yet. Switch Direct Post on in your TikTok app (with video.publish), then connect TikTok again on the Setup page.");
    throw new TikTokError(`TikTok didn't answer as expected (${code || r.status}). Try again in a minute.`);
  }
  const d = body.data ?? {};
  return { account_id: acc.id, direct_post: direct, creator_avatar_url: d.creator_avatar_url, creator_username: d.creator_username,
    creator_nickname: d.creator_nickname, privacy_level_options: d.privacy_level_options ?? [], comment_disabled: Boolean(d.comment_disabled),
    duet_disabled: Boolean(d.duet_disabled), stitch_disabled: Boolean(d.stitch_disabled),
    max_video_post_duration_sec: d.max_video_post_duration_sec, can_post: d.can_post !== false };
}

/** Save one TikTok post's choices (or clear them with clear: true, which sends that post as an inbox draft again). */
export async function confirmPost(env: Env, owner: string, body: { post_id?: string; choices?: Choices; seconds?: number | null; clear?: boolean }):
    Promise<{ ok: true; tiktok_post: unknown }> {
  const db = new Supabase(env);
  if (!body.post_id) throw new TikTokError("Which post? (post_id missing)");
  const rows = await db.select<{ id: string; status: string; social_account_id: string; social_accounts: { platform: string } | null }>(
    "scheduled_posts", `id=eq.${encodeURIComponent(body.post_id)}&select=id,status,social_account_id,social_accounts(platform)`);
  const post = rows[0];
  if (!post || post.social_accounts?.platform !== "tiktok") throw new TikTokError("That isn't a TikTok post.");
  if (["published", "publishing", "cancelled"].includes(post.status)) throw new TikTokError("This post has already gone out or was cancelled; its settings can't change.");
  if (body.clear) {
    await db.update("scheduled_posts", `id=eq.${post.id}`, { tiktok_post: null });
    await db.audit("tiktok_post_settings_cleared", { post: post.id }, "owner");
    return { ok: true, tiktok_post: null };
  }
  const c = body.choices ?? {};
  const creator = await creatorInfo(env, post.social_account_id);
  if (!creator.direct_post) throw new TikTokError("TikTok Direct Post isn't allowed for this connection yet. Switch Direct Post on in your TikTok app (with video.publish), then connect TikTok again on the Setup page.");
  const problem = choiceProblem(c, creator, body.seconds);
  if (problem) throw new TikTokError(problem);
  const saved = {
    privacy_level: c.privacy_level, allow_comment: Boolean(c.allow_comment), allow_duet: Boolean(c.allow_duet), allow_stitch: Boolean(c.allow_stitch),
    disclose: Boolean(c.disclose), your_brand: Boolean(c.disclose && c.your_brand), branded_content: Boolean(c.disclose && c.branded_content),
    consent: true, confirmed_at: new Date().toISOString(), confirmed_by: owner,
    creator_username: creator.creator_username ?? null, creator_nickname: creator.creator_nickname ?? null,
  };
  await db.update("scheduled_posts", `id=eq.${post.id}`, { tiktok_post: saved });
  await db.audit("tiktok_post_settings_confirmed", { post: post.id, privacy_level: saved.privacy_level, disclose: saved.disclose }, "owner");
  return { ok: true, tiktok_post: saved };
}
