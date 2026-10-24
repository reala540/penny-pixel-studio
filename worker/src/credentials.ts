// AI API Manager endpoints (owner only). Keys are encrypted here and stored where the browser can't read them;
// responses only ever include a masked hint like "••••3f9a".

import { decryptJson, encryptJson } from "./crypto";
import { Env, Supabase } from "./supabase";

type Json = Record<string, unknown>;

export class InputError extends Error {}

const SLUG = /^[a-z][a-z0-9_-]{1,31}$/;
const ROLES = new Set(["research_summarizer", "brainstormer", "angle_selector", "scriptwriter", "voice_editor", "critic",
  "claim_checker", "repurposer", "embeddings"]);

export function mask(key: string): string {
  return key.length >= 8 ? `••••${key.slice(-4)}` : "••••";
}

function text(v: unknown, name: string, min: number, max: number): string {
  const s = typeof v === "string" ? v.trim() : "";
  if (s.length < min || s.length > max) throw new InputError(`${name} must be ${min}–${max} characters`);
  return s;
}

function int(v: unknown, name: string, min: number, max: number, fallback: number | null): number | null {
  if (v === undefined || v === null || v === "") return fallback;
  const n = Number(v);
  if (!Number.isInteger(n) || n < min || n > max) throw new InputError(`${name} must be a whole number ${min}–${max}`);
  return n;
}

function apiKey(v: unknown): string {
  const k = typeof v === "string" ? v.trim() : "";
  if (k.length < 8 || k.length > 512 || /\s/.test(k)) throw new InputError("The API key looks incomplete (8–512 characters, no spaces)");
  return k;
}

/** Only public https endpoints may be called with a key. */
export function safeBaseUrl(raw: unknown): string {
  let u: URL;
  try {
    u = new URL(String(raw));
  } catch {
    throw new InputError("Base URL is not a valid address");
  }
  const host = u.hostname.toLowerCase();
  const privateHost = host === "localhost" || host.endsWith(".local") || host.endsWith(".internal") ||
    /^\d+\.\d+\.\d+\.\d+$/.test(host) || host.includes(":") || !host.includes(".");
  if (u.protocol !== "https:" || privateHost || u.username || u.password) {
    throw new InputError("Base URL must be a public https:// address (no IPs, localhost or credentials)");
  }
  return u.toString().replace(/\/+$/, "");
}

async function provider(db: Supabase, name: string) {
  const rows = await db.select<{ name: string; base_url: string }>("ai_providers", `name=eq.${encodeURIComponent(name)}&select=name,base_url`);
  if (!rows.length) throw new InputError("Unknown provider");
  return rows[0];
}

function resolveBase(env: Env, base: string): string {
  return base.replace("${CLOUDFLARE_ACCOUNT_ID}", env.CLOUDFLARE_ACCOUNT_ID ?? "").replace(/\/+$/, "");
}

const PUBLIC_COLUMNS = "id,provider,label,owner_name,authorized_use,key_hint,enabled,priority,weight,quota_group," +
  "separate_account_attested,daily_request_cap,daily_token_cap,monthly_spend_cap_usd,health,created_at";

export async function addCredential(env: Env, body: Json): Promise<Json> {
  const db = new Supabase(env);
  const p = await provider(db, text(body.provider, "Provider", 2, 32));
  const key = apiKey(body.key);
  if (body.authorized !== true) throw new InputError("Confirm that the key's owner authorised this use");
  const separate = body.separate_account === true;
  const row = {
    provider: p.name,
    label: text(body.label, "Label", 1, 80),
    owner_name: text(body.owner_name, "Owner", 1, 80),
    authorized_use: text(body.authorized_use, "Authorised use", 3, 300),
    key_hint: mask(key),
    priority: int(body.priority, "Priority", 1, 1000, 100),
    daily_request_cap: int(body.daily_request_cap, "Daily request cap", 0, 10_000_000, null),
    // One allowance per provider unless this key belongs to a separate account the owner attests to.
    quota_group: separate ? `${p.name}:${crypto.randomUUID().slice(0, 8)}` : p.name,
    separate_account_attested: separate,
  };
  const [cred] = await db.insertReturning<{ id: string }>("ai_credentials", row);
  try {
    await db.insert("ai_credential_secrets", { credential_id: cred.id, ciphertext: await encryptJson(env.TOKEN_ENCRYPTION_KEY, { key }) });
  } catch (e) {
    await db.remove("ai_credentials", `id=eq.${cred.id}`);  // never leave a key-less credential behind
    throw e;
  }
  await db.audit("credential_added", { provider: p.name, label: row.label, owner: row.owner_name, separate }, "owner");
  return (await db.select("ai_credentials", `id=eq.${cred.id}&select=${PUBLIC_COLUMNS}`))[0] as Json;
}

export async function replaceCredential(env: Env, body: Json): Promise<Json> {
  const db = new Supabase(env);
  const id = text(body.id, "Credential", 36, 36);
  const key = apiKey(body.key);
  const rows = await db.select<{ id: string; label: string }>("ai_credentials", `id=eq.${id}&select=id,label`);
  if (!rows.length) throw new InputError("Unknown credential");
  await db.upsert("ai_credential_secrets", { credential_id: id, ciphertext: await encryptJson(env.TOKEN_ENCRYPTION_KEY, { key }),
    updated_at: new Date().toISOString() }, "credential_id");
  await db.update("ai_credentials", `id=eq.${id}`, { key_hint: mask(key), health: "unknown", consecutive_failures: 0,
    circuit_open_until: null, last_error: null });
  await db.audit("credential_replaced", { label: rows[0].label }, "owner");
  return (await db.select("ai_credentials", `id=eq.${id}&select=${PUBLIC_COLUMNS}`))[0] as Json;
}

export async function deleteCredential(env: Env, body: Json): Promise<Json> {
  const db = new Supabase(env);
  const id = text(body.id, "Credential", 36, 36);
  const rows = await db.select<{ label: string }>("ai_credentials", `id=eq.${id}&select=label`);
  if (!rows.length) throw new InputError("Unknown credential");
  await db.remove("ai_credentials", `id=eq.${id}`);  // the encrypted key is deleted with it (cascade)
  await db.audit("credential_removed", { label: rows[0].label }, "owner");
  return { ok: true };
}

/** Calls the provider's /models with the key: proves it works and lists what it can use. */
export async function testCredential(env: Env, body: Json): Promise<Json> {
  const db = new Supabase(env);
  const id = text(body.id, "Credential", 36, 36);
  const rows = await db.select<{ provider: string }>("ai_credentials", `id=eq.${id}&select=provider`);
  if (!rows.length) throw new InputError("Unknown credential");
  const p = await provider(db, rows[0].provider);
  const secret = await db.select<{ ciphertext: string }>("ai_credential_secrets", `credential_id=eq.${id}&select=ciphertext`);
  if (!secret.length) throw new InputError("This credential has no stored key; replace it");
  const { key } = await decryptJson<{ key: string }>(env.TOKEN_ENCRYPTION_KEY, secret[0].ciphertext);
  const base = resolveBase(env, p.base_url);
  let result: { ok: boolean; status: number; message: string; models: string[] };
  if (base.includes("/accounts//")) {
    result = { ok: false, status: 0, message: "Add CLOUDFLARE_ACCOUNT_ID to the Worker (run Deploy Worker) to test Workers AI keys", models: [] };
  } else {
    try {
      const r = await fetch(`${base}/models`, { headers: { Authorization: `Bearer ${key}` }, signal: AbortSignal.timeout(15000) });
      const data = (await r.json().catch(() => ({}))) as { data?: Array<{ id?: string }>; models?: Array<{ name?: string }> };
      const models = (data.data ?? []).map((m) => m.id ?? "").concat((data.models ?? []).map((m) => (m.name ?? "").replace(/^models\//, "")))
        .filter(Boolean).slice(0, 200);
      const message = r.ok ? `Key works · ${models.length} models listed`
        : r.status === 401 || r.status === 403 ? "The provider rejected this key"
        : r.status === 429 ? "Key is valid but rate-limited right now"
        : `Provider answered ${r.status}`;
      result = { ok: r.ok || r.status === 429, status: r.status, message, models };
    } catch (e) {
      result = { ok: false, status: 0, message: `Couldn't reach the provider (${(e as Error).name})`, models: [] };
    }
  }
  await db.update("ai_credentials", `id=eq.${id}`, {
    last_tested_at: new Date().toISOString(), last_test_result: result.message,
    ...(result.models.length ? { models: result.models } : {}),
    health: result.ok ? "healthy" : result.status === 401 || result.status === 403 ? "invalid" : "degraded",
  });
  return result;
}

/** A provider that speaks the OpenAI-compatible API, added from the dashboard. Starts disabled. */
export async function addProvider(env: Env, body: Json): Promise<Json> {
  const db = new Supabase(env);
  const name = text(body.name, "Provider id", 2, 32).toLowerCase();
  if (!SLUG.test(name)) throw new InputError("Provider id: lowercase letters, numbers, - or _");
  const base = safeBaseUrl(body.base_url);
  const models = Array.isArray(body.models) ? body.models : [];
  if (!models.length || models.length > 20) throw new InputError("Add 1–20 models");
  const clean = models.map((m) => {
    const model = text((m as Json).id, "Model id", 1, 120);
    const roles = (Array.isArray((m as Json).roles) ? (m as Json).roles as unknown[] : []).map(String).filter((r) => ROLES.has(r));
    if (!roles.length) throw new InputError(`Pick at least one job for ${model}`);
    return { provider: name, model, roles, priority: int((m as Json).priority, "Priority", 1, 1000, 100),
      daily_request_limit: int((m as Json).daily_request_limit, "Daily limit", 1, 10_000_000, null), roles_custom: true };
  });
  if ((await db.select("ai_providers", `name=eq.${name}&select=name`)).length) throw new InputError("That provider already exists");
  await db.insert("ai_providers", { name, enabled: false, commercial_use_ok: body.commercial_use_ok === true, base_url: base,
    key_env: null, notes: text(body.notes ?? "Added in the AI API Manager", "Notes", 0, 300) });
  for (const m of clean) await db.insert("ai_model_configs", m);
  await db.audit("provider_added", { name, base_url: base, models: clean.map((m) => m.model) }, "owner");
  return { ok: true, name };
}
