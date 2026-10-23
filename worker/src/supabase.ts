// Minimal Supabase REST client for the Worker (service role: server-side only).

export interface Env {
  SUPABASE_URL: string;
  SUPABASE_SERVICE_ROLE_KEY: string;
  SUPABASE_ANON_KEY: string;
  TOKEN_ENCRYPTION_KEY: string;
  DASHBOARD_URL: string;
  GITHUB_REPO: string;
  GITHUB_REF: string;
  GITHUB_TOKEN: string;
  TELEGRAM_BOT_TOKEN?: string;
  TELEGRAM_WEBHOOK_SECRET?: string;
  GOOGLE_CLIENT_ID?: string;
  GOOGLE_CLIENT_SECRET?: string;
  FACEBOOK_APP_ID?: string;
  FACEBOOK_APP_SECRET?: string;
  TIKTOK_CLIENT_KEY?: string;
  TIKTOK_CLIENT_SECRET?: string;
  X_CLIENT_ID?: string;
  X_CLIENT_SECRET?: string;
}

export class Supabase {
  constructor(private env: Env) {}

  private headers(extra: Record<string, string> = {}): Record<string, string> {
    return {
      apikey: this.env.SUPABASE_SERVICE_ROLE_KEY,
      Authorization: `Bearer ${this.env.SUPABASE_SERVICE_ROLE_KEY}`,
      "Content-Type": "application/json",
      ...extra,
    };
  }

  async select<T = Record<string, unknown>>(table: string, query: string): Promise<T[]> {
    const r = await fetch(`${this.env.SUPABASE_URL}/rest/v1/${table}?${query}`, { headers: this.headers() });
    if (!r.ok) throw new Error(`select ${table}: ${r.status} ${await r.text()}`);
    return (await r.json()) as T[];
  }

  async upsert(table: string, row: Record<string, unknown>, onConflict: string): Promise<void> {
    const r = await fetch(`${this.env.SUPABASE_URL}/rest/v1/${table}?on_conflict=${onConflict}`, {
      method: "POST",
      headers: this.headers({ Prefer: "resolution=merge-duplicates,return=minimal" }),
      body: JSON.stringify(row),
    });
    if (!r.ok) throw new Error(`upsert ${table}: ${r.status} ${await r.text()}`);
  }

  async update(table: string, filter: string, patch: Record<string, unknown>): Promise<void> {
    const r = await fetch(`${this.env.SUPABASE_URL}/rest/v1/${table}?${filter}`, {
      method: "PATCH",
      headers: this.headers({ Prefer: "return=minimal" }),
      body: JSON.stringify(patch),
    });
    if (!r.ok) throw new Error(`update ${table}: ${r.status} ${await r.text()}`);
  }

  async insert(table: string, row: Record<string, unknown>): Promise<void> {
    const r = await fetch(`${this.env.SUPABASE_URL}/rest/v1/${table}`, {
      method: "POST",
      headers: this.headers({ Prefer: "return=minimal" }),
      body: JSON.stringify(row),
    });
    if (!r.ok) throw new Error(`insert ${table}: ${r.status} ${await r.text()}`);
  }

  async setting<T>(key: string): Promise<T | null> {
    const rows = await this.select<{ value: T }>("settings", `key=eq.${encodeURIComponent(key)}&select=value`);
    return rows.length ? rows[0].value : null;
  }

  async putSetting(key: string, value: unknown): Promise<void> {
    await this.upsert("settings", { key, value }, "key");
  }

  /** Validates a dashboard session token and confirms that user is the studio owner. */
  async ownerFromToken(accessToken: string | null): Promise<string | null> {
    if (!accessToken) return null;
    const r = await fetch(`${this.env.SUPABASE_URL}/auth/v1/user`, {
      headers: { apikey: this.env.SUPABASE_ANON_KEY, Authorization: `Bearer ${accessToken}` },
    });
    if (!r.ok) return null;
    const user = (await r.json()) as { id?: string };
    if (!user.id) return null;
    const owners = await this.select<{ user_id: string }>("app_owner", `user_id=eq.${user.id}&select=user_id`);
    return owners.length ? user.id : null;
  }

  async audit(action: string, details: Record<string, unknown>, actor = "worker"): Promise<void> {
    await this.insert("audit_logs", { actor, action, details });
  }
}
