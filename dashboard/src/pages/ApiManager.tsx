import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronDown, FlaskConical, KeyRound, Plus, RefreshCw, Trash2 } from "lucide-react";
import { FormEvent, useMemo, useState } from "react";
import ClearButton from "../components/ClearButton";
import { Confirm, ErrorNote, Loading, PageHeader, useToast } from "../components/ui";
import { must, queueJob, useSetting } from "../lib/api";
import { isCleared, useCleared } from "../lib/clear";
import { useKeyCheck } from "../lib/readiness";
import { callWorker, supabase, workerUrl } from "../lib/supabase";

type Provider = {
  name: string; enabled: boolean; base_url: string; key_env: string | null; key_strategy: string; max_concurrency: number;
  request_timeout_s: number; max_retries: number; use_env_key: boolean; circuit_open_until: string | null;
  last_success_at: string | null; last_error: string | null; commercial_use_ok: boolean;
};
type Cred = {
  id: string; provider: string; label: string; owner_name: string; authorized_use: string; key_hint: string; enabled: boolean;
  priority: number; weight: number; quota_group: string; separate_account_attested: boolean; daily_request_cap: number | null;
  daily_token_cap: number | null; monthly_spend_cap_usd: number | null; input_usd_per_mtok: number | null;
  output_usd_per_mtok: number | null; max_concurrency: number; health: string; circuit_open_until: string | null;
  last_success_at: string | null; last_error: string | null; last_error_at: string | null; last_tested_at: string | null;
  last_test_result: string | null; models: string[];
};
type Model = { provider: string; model: string; roles: string[]; enabled: boolean; priority: number; roles_custom: boolean;
  pause_reason?: "retired" | "payment" | null; next_check_at?: string | null; checks?: number; pause_detail?: string | null };
type Use = { provider: string; credential_id: string | null; success: boolean; error: string | null; latency_ms: number | null;
  input_tokens: number; output_tokens: number; cost_usd: number; cost_source: string; created_at: string };
type Stats = { today: number; month: number; failed: number; limited: number; latency: number | null; tokens: number; cost: number; estimated: boolean };

const STRATEGY: Record<string, string> = {
  priority: "Priority: best key first while healthy and within limits",
  round_robin: "Round robin: take turns in order",
  least_utilized: "Least utilised: most remaining capacity first",
  health: "Health: fewest recent errors first",
  weighted: "Weighted: split traffic by the percentages you set",
};
const ROLE_LABEL: Record<string, string> = {
  research_summarizer: "Evidence scout", brainstormer: "Idea council", angle_selector: "Hook selector", scriptwriter: "Scriptwriter",
  voice_editor: "Voice editor", critic: "Critic", claim_checker: "Claim checker", repurposer: "Distribution editor", embeddings: "Embeddings",
};
const HEALTH_TONE: Record<string, string> = {
  healthy: "bg-penny-soft text-penny", unknown: "bg-sunken text-muted", degraded: "bg-gold/15 text-ink",
  resting: "bg-gold/15 text-ink", invalid: "bg-alert-soft text-alert", exhausted: "bg-alert-soft text-alert",
};

/** What each provider's terms say about using several (borrowed) keys. A guide only: nothing is blocked. */
export const KEY_GUIDE: Record<string, { tone: "more" | "one" | "no" | "check"; label: string; note: string }> = {
  gemini: { tone: "more", label: "Add more keys", note: "Best-quality writer. Each key must be a different person's own Google project; keys from one project share its limit." },
  cloudflare: { tone: "more", label: "Add more keys", note: "Always available. Each account gets its own 10,000 free units a day." },
  zai: { tone: "more", label: "Add more keys", note: "Each key handles one request at a time, so extra keys cut waiting the most." },
  cerebras: { tone: "more", label: "Add more keys", note: "Very fast. No rule against several keys was found; each owner should check their own terms." },
  sambanova: { tone: "more", label: "Add more keys", note: "Very fast. No rule against several keys was found; each owner should check their own terms." },
  groq: { tone: "one", label: "One key only", note: "Groq's usage policy reportedly bans using several accounts to go over its limits. Keep one key." },
  nvidia: { tone: "no", label: "Borrowed keys not allowed", note: "NVIDIA's free trial is for testing, not for publishing content. Not suitable for posting, borrowed or not." },
  mistral: { tone: "no", label: "Borrowed keys not allowed", note: "Mistral's terms ban sharing keys between people and making several accounts to get around limits." },
};
const GUIDE_TONE = { more: "bg-penny-soft text-penny", one: "bg-gold/15 text-ink", no: "bg-alert-soft text-alert", check: "bg-sunken text-muted" };
const guideFor = (name: string) => KEY_GUIDE[name] ?? { tone: "check" as const, label: "Check the owner's terms", note: "No rule was found either way. Before adding a borrowed key, its owner should check this provider's terms." };

function stats(rows: Use[]): Stats {
  const today = new Date().toISOString().slice(0, 10);
  const monthStart = new Date(new Date().getUTCFullYear(), new Date().getUTCMonth(), 1).toISOString();
  const lat = rows.filter((r) => r.latency_ms != null && r.success).map((r) => r.latency_ms as number);
  const month = rows.filter((r) => r.created_at >= monthStart);
  return {
    today: rows.filter((r) => r.created_at.slice(0, 10) === today).length,
    month: month.length,
    failed: rows.filter((r) => !r.success).length,
    limited: rows.filter((r) => (r.error ?? "").startsWith("429")).length,
    latency: lat.length ? Math.round(lat.reduce((a, b) => a + b, 0) / lat.length) : null,
    tokens: rows.reduce((a, r) => a + r.input_tokens + r.output_tokens, 0),
    cost: month.reduce((a, r) => a + Number(r.cost_usd || 0), 0),
    estimated: month.some((r) => r.cost_source === "estimated"),
  };
}

function when(iso: string | null): string {
  return iso ? new Date(iso).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" }) : "never";
}

export default function ApiManager() {
  const qc = useQueryClient();
  const toast = useToast();
  const data = useQuery({
    queryKey: ["api-manager"],
    refetchInterval: 30_000,
    queryFn: async () => {
      const since = new Date(Date.now() - 30 * 86400_000).toISOString();
      const [providers, creds, models, usage] = await Promise.all([
        must(supabase.from("ai_providers").select("*").order("name")),
        must(supabase.from("ai_credentials").select("id,provider,label,owner_name,authorized_use,key_hint,enabled,priority,weight,quota_group,separate_account_attested,daily_request_cap,daily_token_cap,monthly_spend_cap_usd,input_usd_per_mtok,output_usd_per_mtok,max_concurrency,health,circuit_open_until,last_success_at,last_error,last_error_at,last_tested_at,last_test_result,models").order("priority")),
        must(supabase.from("ai_model_configs").select("provider,model,roles,enabled,priority,roles_custom,pause_reason,next_check_at,checks,pause_detail").order("priority")),
        must(supabase.from("provider_usage").select("provider,credential_id,success,error,latency_ms,input_tokens,output_tokens,cost_usd,cost_source,created_at").eq("service", "llm").gte("created_at", since).order("created_at", { ascending: false }).limit(5000)),
      ]);
      return { providers: providers as Provider[], creds: creds as Cred[], models: models as Model[], usage: usage as Use[] };
    },
  });
  const check = useSetting<{ checked_at?: string; results?: { provider: string; status: string; note?: string; error?: string }[] } | null>("provider_check", null).data;
  const refresh = () => qc.invalidateQueries({ queryKey: ["api-manager"] });
  const cleared = useCleared();
  // "Reset usage stats" only changes what this page counts; the studio's daily limits still use every call.
  const usage = useMemo(() => (data.data?.usage ?? []).filter((u) => !isCleared(cleared.map, "api_stats", u.created_at)), [data.data, cleared.map]);
  const errorsSince = cleared.map.api_errors;

  const totals = useMemo(() => stats(usage), [usage]);
  if (data.isLoading) return <><PageHeader title="AI API Manager" /><Loading /></>;

  return (
    <>
      <PageHeader title="AI API Manager" intro="Keys for each AI provider, how they share the work, their limits and how they're doing. Full keys never come back to this page: only the last 4 characters." />
      <ErrorNote error={data.error} onRetry={() => data.refetch()} retrying={data.isFetching} />
      {!workerUrl && <p role="alert" className="mb-4 rounded-lg bg-alert-soft px-3 py-2 text-sm text-alert">Configuration required: adding, testing and removing keys needs the Worker (VITE_WORKER_URL). You can still change limits and strategies.</p>}

      <dl className="mb-6 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
        {[
          ["Providers enabled", `${(data.data?.providers ?? []).filter((p) => p.enabled).length}`],
          ["Keys added here", `${(data.data?.creds ?? []).length}`],
          ["Calls today", `${totals.today}`],
          ["Failures (30 days)", `${totals.failed}`],
          ["Rate-limit events", `${totals.limited}`],
          ["Cost this month", totals.estimated ? `≈ $${totals.cost.toFixed(2)}` : "not tracked"],
        ].map(([k, v]) => [k, data.isSuccess ? v : "—"]).map(([k, v]) => (
          <div key={k} className="rounded-xl border border-line bg-surface px-4 py-3"><dt className="text-xs text-muted">{k}</dt><dd className="mt-1 font-display text-lg font-semibold tabular-nums text-ink">{v}</dd></div>
        ))}
      </dl>
      <div className="mb-3 flex flex-wrap gap-2">
        <ClearButton label="Reset usage stats" title="Reset the usage numbers on this page?" done="Usage stats reset"
          body="Calls, failures, rate-limit events, tokens and cost start counting from now on this page. Your daily key limits still count every call made today, and nothing is deleted. You can undo this."
          onClear={() => cleared.clear("api_stats")} />
        <ClearButton label="Clear errors" title="Clear the error messages?" done="Errors cleared"
          body="Old error messages are hidden from the keys and providers. New errors still show. Key health isn't changed: press Test on a key to re-check it."
          onClear={() => cleared.clear("api_errors")} />
      </div>
      <p className="mb-6 text-xs text-muted">
        <strong className="text-ink">Observed</strong> = counted by this studio from its own calls. <strong className="text-ink">Estimated</strong> = tokens × the prices you enter for a key.
        Providers don't report usage or bills to the studio, so check their own consoles for official numbers.
      </p>

      <AddKey providers={data.data?.providers ?? []} onDone={refresh} />

      <div className="mt-8 space-y-6">
        {[...(data.data?.providers ?? [])].sort((a, b) => Number(b.enabled) - Number(a.enabled) || a.name.localeCompare(b.name)).map((p) => (
          <ProviderCard key={p.name} p={p} creds={(data.data?.creds ?? []).filter((c) => c.provider === p.name)}
            models={(data.data?.models ?? []).filter((m) => m.provider === p.name)}
            usage={usage.filter((u) => u.provider === p.name)} errorsSince={errorsSince}
            envCheck={check?.results?.find((r) => r.provider === p.name)} onChange={refresh} toast={toast} />
        ))}
      </div>

      <AddProvider onDone={refresh} />
    </>
  );
}

function AddKey({ providers, onDone }: { providers: Provider[]; onDone: () => void }) {
  const toast = useToast();
  const [open, setOpen] = useState(false);
  const [f, setF] = useState({ provider: "gemini", label: "", owner_name: "", authorized_use: "Writing and checking scripts for Penny & Pixel Studio", key: "", priority: "100", daily_request_cap: "", authorized: false, separate_account: false });
  const add = useMutation({
    mutationFn: () => callWorker("/api/credentials/add", { ...f, priority: Number(f.priority) || 100, daily_request_cap: f.daily_request_cap === "" ? null : Number(f.daily_request_cap) }),
    onSuccess: () => { toast("Key saved (encrypted). Test it below."); setF({ ...f, key: "", label: "" }); setOpen(false); onDone(); },
    onError: (e) => toast((e as Error).message, "bad"),
  });
  const set = (k: keyof typeof f) => (e: { target: { value: string; checked?: boolean; type?: string } }) =>
    setF({ ...f, [k]: e.target.type === "checkbox" ? Boolean(e.target.checked) : e.target.value });
  const submit = (e: FormEvent) => { e.preventDefault(); add.mutate(); };
  return (
    <section aria-labelledby="addkey-title" className="rounded-xl border border-line bg-surface">
      <button className="flex w-full items-center gap-2 px-4 py-3 text-left" onClick={() => setOpen(!open)} aria-expanded={open}>
        <Plus size={16} aria-hidden /><h2 id="addkey-title" className="text-sm font-semibold text-ink">Add an API key</h2>
        <ChevronDown size={14} className={`ml-auto ${open ? "rotate-180" : ""}`} aria-hidden />
      </button>
      {open && (
        <form onSubmit={submit} className="grid gap-3 border-t border-line p-4 sm:grid-cols-2" autoComplete="off">
          <label className="text-sm">Provider<select aria-label="Provider" className="field mt-1" value={f.provider} onChange={set("provider")}>
            {providers.map((p) => <option key={p.name} value={p.name}>{p.name}</option>)}</select></label>
          <label className="text-sm">Label<input className="field mt-1" required maxLength={80} value={f.label} onChange={set("label")} placeholder="e.g. Gemini · Sam" /></label>
          <label className="text-sm">Whose key is it?<input className="field mt-1" required maxLength={80} value={f.owner_name} onChange={set("owner_name")} placeholder="Name of the account owner" /></label>
          <label className="text-sm">What they allowed it to be used for<input className="field mt-1" required minLength={3} maxLength={300} value={f.authorized_use} onChange={set("authorized_use")} /></label>
          <label className="text-sm sm:col-span-2">API key<input className="field mt-1 font-mono" type="password" required minLength={8} maxLength={512} value={f.key} onChange={set("key")} autoComplete="new-password" spellCheck={false} placeholder="Paste the key (sent once to the Worker, then stored encrypted)" /></label>
          <label className="text-sm">Priority (1 = first)<input className="field mt-1" type="number" min={1} max={1000} value={f.priority} onChange={set("priority")} /></label>
          <label className="text-sm">Daily request limit (optional)<input className="field mt-1" type="number" min={0} value={f.daily_request_cap} onChange={set("daily_request_cap")} /></label>
          <label className="flex items-start gap-2 text-sm sm:col-span-2"><input type="checkbox" className="mt-1" checked={f.authorized} onChange={set("authorized")} required />
            <span>The owner of this key has authorised this use, and it's within the provider's terms for their account.</span></label>
          <label className="flex items-start gap-2 text-sm sm:col-span-2"><input type="checkbox" className="mt-1" checked={f.separate_account} onChange={set("separate_account")} />
            <span>This key belongs to a <strong>separate account with its own allowance</strong>. Leave this off for keys from the same account or project:
              those share one rate limit, so when one is throttled the studio rests them all instead of switching between them.
              Providers such as Google and Groq don't allow using extra accounts to get around free limits.</span></label>
          <div className="sm:col-span-2"><button className="btn-primary" disabled={add.isPending || !workerUrl || !f.authorized}>{add.isPending ? "Saving…" : "Save key"}</button></div>
        </form>
      )}
    </section>
  );
}

function ProviderCard({ p, creds, models, usage, envCheck, onChange, toast, errorsSince }: {
  p: Provider; creds: Cred[]; models: Model[]; usage: Use[]; envCheck?: { status: string; note?: string; error?: string; models?: { model: string; status: string; error?: string }[] };
  onChange: () => void; toast: ReturnType<typeof useToast>; errorsSince?: string;
}) {
  const guide = guideFor(p.name);
  const freshFailure = !errorsSince || usage.some((u) => !u.success && Date.parse(u.created_at) > Date.parse(errorsSince));
  const [showModels, setShowModels] = useState(false);
  const [expanded, setExpanded] = useState(p.enabled || creds.length > 0);  // switched-off providers start folded
  const save = useMutation({
    mutationFn: async (patch: Partial<Provider>) => must(supabase.from("ai_providers").update(patch).eq("name", p.name)),
    onSuccess: () => { toast("Saved"); onChange(); },
    onError: (e) => toast((e as Error).message, "bad"),
  });
  const resting = p.circuit_open_until && Date.parse(p.circuit_open_until) > Date.now();
  const envStats = stats(usage.filter((u) => !u.credential_id));
  return (
    <section aria-labelledby={`prov-${p.name}`} className="rounded-xl border border-line bg-surface">
      <header className="flex flex-wrap items-center gap-3 border-b border-line px-4 py-3">
        <KeyRound size={16} className="text-muted" aria-hidden />
        <h2 id={`prov-${p.name}`} className="font-display text-base font-semibold text-ink">{p.name}</h2>
        <span className="text-xs text-muted">{p.key_env ? "built-in" : "added here"}</span>
        <span className={`rounded-md px-2 py-0.5 text-xs font-medium ${GUIDE_TONE[guide.tone]}`} title={guide.note}>{guide.label}</span>
        {resting && <span className="rounded-md bg-gold/15 px-2 py-0.5 text-xs text-ink">resting until {when(p.circuit_open_until)}</span>}
        <label className="ml-auto flex items-center gap-2 text-sm"><input type="checkbox" checked={p.enabled} onChange={(e) => { save.mutate({ enabled: e.target.checked }); if (e.target.checked) setExpanded(true); }} />Use this provider</label>
        <button className="inline-flex items-center gap-1 text-sm text-muted hover:text-ink" onClick={() => setExpanded(!expanded)} aria-expanded={expanded} aria-controls={`prov-body-${p.name}`}>
          {expanded ? "Hide" : "Show"} details <ChevronDown size={14} className={expanded ? "rotate-180" : ""} aria-hidden />
        </button>
      </header>
      {expanded && <div id={`prov-body-${p.name}`}>
      <div className="grid gap-3 px-4 py-3 text-sm sm:grid-cols-2 lg:grid-cols-4">
        <label className="lg:col-span-2">How keys share the work
          <select aria-label="How keys share the work" className="field mt-1" value={p.key_strategy} onChange={(e) => save.mutate({ key_strategy: e.target.value })}>
            {Object.entries(STRATEGY).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select></label>
        <NumberField label="Parallel requests (provider)" value={p.max_concurrency} min={1} max={32} onSave={(v) => v != null && save.mutate({ max_concurrency: v })} />
        <NumberField label="Timeout (seconds)" value={p.request_timeout_s} min={10} max={600} onSave={(v) => v != null && save.mutate({ request_timeout_s: v })} />
        <NumberField label="Retries on temporary errors" value={p.max_retries} min={0} max={5} onSave={(v) => v != null && save.mutate({ max_retries: v })} />
        {p.key_env && <label className="flex items-center gap-2 self-end pb-2"><input type="checkbox" checked={p.use_env_key} onChange={(e) => save.mutate({ use_env_key: e.target.checked })} />Use the GitHub secret {p.key_env}</label>}
      </div>
      <p className={`mx-4 mb-3 rounded-lg px-3 py-2 text-xs ${GUIDE_TONE[guide.tone]}`}><strong>{guide.label}.</strong> {guide.note}</p>
      {p.last_error && freshFailure && <p className="px-4 pb-2 text-xs text-muted">Last provider error: {p.last_error}</p>}

      <div className="overflow-x-auto">
        <table className="w-full min-w-[760px] text-left text-sm">
          <thead className="border-y border-line bg-sunken/50 text-xs text-muted">
            <tr><th className="px-4 py-2 font-medium">Key</th><th className="px-2 py-2 font-medium">Health</th><th className="px-2 py-2 font-medium">Limits</th>
              <th className="px-2 py-2 font-medium">Observed (30 days)</th><th className="px-2 py-2 font-medium">Last activity</th><th className="px-4 py-2 font-medium text-right">Actions</th></tr>
          </thead>
          <tbody className="divide-y divide-line">
            {p.key_env && (
              <tr>
                <td className="px-4 py-3"><p className="font-medium text-ink">GitHub secret</p><p className="font-mono text-xs text-muted">{p.key_env}</p></td>
                <td className="px-2 py-3"><span className={`rounded-md px-2 py-0.5 text-xs ${envCheck?.status === "ok" ? HEALTH_TONE.healthy : envCheck?.status === "failed" ? HEALTH_TONE.invalid : HEALTH_TONE.unknown}`}>{envCheck?.status ?? "not checked"}</span></td>
                <td className="px-2 py-3 text-xs text-muted">Provider's own limits</td>
                <td className="px-2 py-3"><StatsCell s={envStats} /></td>
                <td className="px-2 py-3 text-xs text-muted">{envCheck?.note ?? envCheck?.error ?? "Not checked yet"}
                  {envCheck?.status === "ok" && envCheck.error && <span className="block text-alert">Not working: {envCheck.error.slice(0, 160)}</span>}</td>
                <td className="px-4 py-3 text-right text-xs text-muted">
                  {p.use_env_key ? <div className="flex flex-wrap justify-end gap-1"><EnvKeyTest provider={p.name} /><EnvKeyReplace provider={p.name} secret={p.key_env} onChange={onChange} /></div>
                    : <span>Not in use: a key saved here replaced it</span>}</td>
              </tr>
            )}
            {creds.map((c) => <CredRow key={c.id} c={errorsSince && c.last_error_at && Date.parse(c.last_error_at) <= Date.parse(errorsSince) ? { ...c, last_error: null } : c}
              strategy={p.key_strategy} usage={usage.filter((u) => u.credential_id === c.id)} onChange={onChange} toast={toast} />)}
            {!creds.length && !p.key_env && <tr><td colSpan={6} className="px-4 py-3 text-sm text-muted">No keys yet: add one above.</td></tr>}
          </tbody>
        </table>
      </div>

      <div className="border-t border-line px-4 py-3">
        <button className="inline-flex items-center gap-1 text-sm text-muted hover:text-ink" onClick={() => setShowModels(!showModels)} aria-expanded={showModels}>
          Models and the jobs they do ({models.length}) <ChevronDown size={14} className={showModels ? "rotate-180" : ""} aria-hidden />
        </button>
        {showModels && <ModelRoles models={models} supported={[...new Set(creds.flatMap((c) => c.models ?? []))]} onChange={onChange} toast={toast} />}
      </div>
      </div>}
    </section>
  );
}

/** A GitHub-secret key can only be tested by the engine on GitHub: this tests this one service there. */
function EnvKeyTest({ provider }: { provider: string }) {
  const toast = useToast();
  const keyCheck = useKeyCheck();
  const run = useMutation({
    mutationFn: () => queueJob("check_providers", { input: { provider } }),
    onSuccess: () => { keyCheck.refresh(); toast(`Testing ${provider}'s models. The result appears here in a few minutes.`); },
    onError: (e) => toast((e as Error).message, "bad"),
  });
  return (
    <button className="btn-quiet px-2 py-1 text-xs" disabled={keyCheck.running || run.isPending}
      title={keyCheck.running ? "A key test is already running" : `Test ${provider} only`} onClick={() => run.mutate()}>
      <FlaskConical size={12} aria-hidden />{keyCheck.running || run.isPending ? "Testing…" : "Test"}
    </button>
  );
}

/** Use a new key saved here instead of the GitHub secret: it takes effect on the next run. */
function EnvKeyReplace({ provider, secret, onChange }: { provider: string; secret: string; onChange: () => void }) {
  const toast = useToast();
  const [open, setOpen] = useState(false);
  const [key, setKey] = useState("");
  const replace = useMutation({
    mutationFn: async () => {
      const cred = await callWorker<{ id: string }>("/api/credentials/replace-env", { provider, key });
      return callWorker<{ ok: boolean; message: string }>("/api/credentials/test", { id: cred.id });
    },
    onSuccess: (r) => { toast(`New key saved and in use. ${r.message}`, r.ok ? undefined : "bad"); setKey(""); setOpen(false); onChange(); },
    onError: (e) => toast((e as Error).message, "bad"),
  });
  if (!open) return <button className="btn-quiet px-2 py-1 text-xs" onClick={() => setOpen(true)} disabled={!workerUrl}><RefreshCw size={12} aria-hidden />Replace</button>;
  return (
    <form className="mt-2 flex flex-col items-end gap-1" onSubmit={(e) => { e.preventDefault(); replace.mutate(); }} autoComplete="off">
      <input className="field w-56 font-mono" type="password" minLength={8} maxLength={512} value={key} onChange={(e) => setKey(e.target.value)}
        placeholder="Paste the new key" aria-label={`New ${provider} key`} autoComplete="new-password" />
      <span className="max-w-56 text-left text-[11px] leading-4 text-muted">Saved encrypted here and used instead of the GitHub secret {secret}. You can delete that secret in GitHub later.</span>
      <span className="flex gap-1">
        <button type="button" className="btn-quiet px-2 py-1 text-xs" onClick={() => { setOpen(false); setKey(""); }}>Cancel</button>
        <button className="btn-primary px-2 py-1 text-xs" disabled={replace.isPending || key.length < 8}>{replace.isPending ? "Saving…" : "Save and use"}</button>
      </span>
    </form>
  );
}

function StatsCell({ s }: { s: Stats }) {
  return (
    <div className="text-xs leading-5 text-muted">
      <span className="text-ink">{s.today}</span> today · {s.month} this month<br />
      {s.failed} failed · {s.limited} rate-limited{s.latency != null ? ` · ${(s.latency / 1000).toFixed(1)}s avg` : ""}<br />
      {s.tokens.toLocaleString()} tokens{s.estimated ? ` · ≈ $${s.cost.toFixed(2)} estimated` : ""}
    </div>
  );
}

function NumberField({ label, value, min, max, step = 1, onSave, empty = false }: {
  label: string; value: number | null; min: number; max?: number; step?: number; onSave: (v: number | null) => void; empty?: boolean;
}) {
  const [v, setV] = useState(value == null ? "" : String(value));
  const commit = () => {
    if (v === "" && empty) { if (value != null) onSave(null); return; }
    const n = Number(v);
    if (!Number.isFinite(n) || n < min || (max != null && n > max)) { setV(value == null ? "" : String(value)); return; }
    if (n !== value) onSave(n);
  };
  return (
    <label className="text-sm">{label}
      <input className="field mt-1" type="number" inputMode="decimal" min={min} max={max} step={step} value={v}
        onChange={(e) => setV(e.target.value)} onBlur={commit} onKeyDown={(e) => e.key === "Enter" && (e.currentTarget as HTMLInputElement).blur()}
        placeholder={empty ? "no limit" : undefined} />
    </label>
  );
}

function CredRow({ c, strategy, usage, onChange, toast }: { c: Cred; strategy: string; usage: Use[]; onChange: () => void; toast: ReturnType<typeof useToast> }) {
  const [edit, setEdit] = useState(false);
  const [confirm, setConfirm] = useState(false);
  const [replacing, setReplacing] = useState(false);
  const [newKey, setNewKey] = useState("");
  const update = useMutation({
    mutationFn: async (patch: Partial<Cred>) => must(supabase.from("ai_credentials").update(patch).eq("id", c.id)),
    onSuccess: () => { toast("Saved"); onChange(); },
    onError: (e) => toast((e as Error).message, "bad"),
  });
  const test = useMutation({
    mutationFn: () => callWorker<{ ok: boolean; message: string }>("/api/credentials/test", { id: c.id }),
    onSuccess: (r) => { toast(r.message, r.ok ? undefined : "bad"); onChange(); },
    onError: (e) => toast((e as Error).message, "bad"),
  });
  const replace = useMutation({
    mutationFn: () => callWorker("/api/credentials/replace", { id: c.id, key: newKey }),
    onSuccess: () => { toast("Key replaced"); setNewKey(""); setReplacing(false); onChange(); },
    onError: (e) => toast((e as Error).message, "bad"),
  });
  const remove = useMutation({
    mutationFn: () => callWorker("/api/credentials/delete", { id: c.id }),
    onSuccess: () => { toast("Key removed"); onChange(); },
    onError: (e) => toast((e as Error).message, "bad"),
  });
  const s = stats(usage);
  const resting = c.circuit_open_until && Date.parse(c.circuit_open_until) > Date.now();
  return (
    <>
      <tr className={c.enabled ? "" : "opacity-60"}>
        <td className="px-4 py-3">
          <p className="font-medium text-ink">{c.label}</p>
          <p className="text-xs text-muted"><span className="font-mono">{c.key_hint}</span> · {c.owner_name}{c.separate_account_attested ? " · separate account" : ""}</p>
        </td>
        <td className="px-2 py-3"><span className={`rounded-md px-2 py-0.5 text-xs ${HEALTH_TONE[c.health] ?? HEALTH_TONE.unknown}`}>{c.health}</span>
          {resting && <p className="mt-1 text-xs text-muted">until {when(c.circuit_open_until)}</p>}</td>
        <td className="px-2 py-3 text-xs text-muted">P{c.priority}{strategy === "weighted" ? ` · weight ${c.weight}` : ""}<br />
          {c.daily_request_cap != null ? `${c.daily_request_cap}/day` : "no daily cap"}{c.monthly_spend_cap_usd != null ? ` · $${c.monthly_spend_cap_usd}/mo` : ""}</td>
        <td className="px-2 py-3"><StatsCell s={s} /></td>
        <td className="px-2 py-3 text-xs text-muted">OK {when(c.last_success_at)}<br />{c.last_error ? <span className="text-alert">{c.last_error}</span> : c.last_test_result ?? ""}</td>
        <td className="px-4 py-3 text-right">
          <div className="flex flex-wrap justify-end gap-1">
            <label className="mr-1 flex items-center gap-1 text-xs"><input type="checkbox" checked={c.enabled} onChange={(e) => update.mutate({ enabled: e.target.checked })} />On</label>
            <button className="btn-quiet px-2 py-1 text-xs" onClick={() => test.mutate()} disabled={test.isPending || !workerUrl}><FlaskConical size={12} aria-hidden />{test.isPending ? "Testing…" : "Test"}</button>
            <button className="btn-quiet px-2 py-1 text-xs" onClick={() => setEdit(!edit)} aria-expanded={edit}>Limits</button>
            <button className="btn-quiet px-2 py-1 text-xs" onClick={() => setReplacing(!replacing)} disabled={!workerUrl}><RefreshCw size={12} aria-hidden />Replace</button>
            <button className="btn-danger px-2 py-1 text-xs" onClick={() => setConfirm(true)} disabled={!workerUrl}><Trash2 size={12} aria-hidden />Remove</button>
          </div>
        </td>
      </tr>
      {(edit || replacing) && (
        <tr><td colSpan={6} className="bg-sunken/40 px-4 py-3">
          {replacing && (
            <form className="mb-3 flex flex-col gap-2 sm:flex-row" onSubmit={(e) => { e.preventDefault(); replace.mutate(); }} autoComplete="off">
              <label className="flex-1 text-sm"><span className="sr-only">New key</span>
                <input className="field font-mono" type="password" minLength={8} maxLength={512} value={newKey} onChange={(e) => setNewKey(e.target.value)} placeholder="Paste the new key" autoComplete="new-password" /></label>
              <button className="btn-quiet" disabled={replace.isPending || newKey.length < 8}>Replace key</button>
            </form>
          )}
          {edit && (
            <div className="grid gap-3 sm:grid-cols-3 lg:grid-cols-5">
              <NumberField label="Priority (1 = first)" value={c.priority} min={1} max={1000} onSave={(v) => update.mutate({ priority: v ?? 100 })} />
              <NumberField label="Weight % (weighted)" value={c.weight} min={0} max={100} onSave={(v) => update.mutate({ weight: v ?? 1 })} />
              <NumberField label="Requests per day" value={c.daily_request_cap} min={0} empty onSave={(v) => update.mutate({ daily_request_cap: v })} />
              <NumberField label="Tokens per day" value={c.daily_token_cap} min={0} empty onSave={(v) => update.mutate({ daily_token_cap: v })} />
              <NumberField label="Parallel requests" value={c.max_concurrency} min={1} max={16} onSave={(v) => update.mutate({ max_concurrency: v ?? 2 })} />
              <NumberField label="Monthly cap (USD)" value={c.monthly_spend_cap_usd} min={0} step={0.01} empty onSave={(v) => update.mutate({ monthly_spend_cap_usd: v })} />
              <NumberField label="Input $ per 1M tokens" value={c.input_usd_per_mtok} min={0} step={0.0001} empty onSave={(v) => update.mutate({ input_usd_per_mtok: v })} />
              <NumberField label="Output $ per 1M tokens" value={c.output_usd_per_mtok} min={0} step={0.0001} empty onSave={(v) => update.mutate({ output_usd_per_mtok: v })} />
              <p className="text-xs leading-5 text-muted sm:col-span-3 lg:col-span-2">A monthly cap only works with prices entered: the studio estimates cost from tokens. Authorised use: {c.authorized_use}</p>
            </div>
          )}
        </td></tr>
      )}
      <Confirm open={confirm} title={`Remove ${c.label}?`} body="The encrypted key is deleted. Usage history stays, without the key." confirmLabel="Remove key" danger
        onConfirm={() => { setConfirm(false); remove.mutate(); }} onCancel={() => setConfirm(false)} />
    </>
  );
}

const PAUSE_WHY = { retired: "the provider says it reached its end of life", payment: "it isn't free on your plan" };

/** A model that paused itself: why, when it's re-tested, and a way to try it now. */
function PausedNote({ m, onChange, toast }: { m: Model; onChange: () => void; toast: ReturnType<typeof useToast> }) {
  const retest = useMutation({
    mutationFn: async () => must(supabase.from("ai_model_configs").update({ next_check_at: new Date().toISOString() }).eq("provider", m.provider).eq("model", m.model)),
    onSuccess: () => { toast("It will be re-tested on the next engine run (within about 15 minutes when work is queued, or tonight)."); onChange(); },
    onError: (e) => toast((e as Error).message, "bad"),
  });
  return (
    <p className="mb-2 rounded-md bg-gold/15 px-2 py-1.5 text-xs text-ink">
      <strong>Paused by itself:</strong> {PAUSE_WHY[m.pause_reason!]}. {m.next_check_at
        ? <>Re-tested {new Date(m.next_check_at).toLocaleString()} ({m.checks ?? 0} re-test{m.checks === 1 ? "" : "s"} so far); it comes back by itself when it works.</>
        : <>Re-tests finished without success ({m.checks} tries): switch it off, remove it, or replace the key.</>}
      {" "}<button type="button" className="underline" onClick={() => retest.mutate()} disabled={retest.isPending}>Re-test soon</button>
    </p>
  );
}

function ModelRoles({ models, supported, onChange, toast }: { models: Model[]; supported: string[]; onChange: () => void; toast: ReturnType<typeof useToast> }) {
  const save = useMutation({
    mutationFn: async ({ m, roles }: { m: Model; roles: string[] }) =>
      must(supabase.from("ai_model_configs").update({ roles, roles_custom: true }).eq("provider", m.provider).eq("model", m.model)),
    onSuccess: () => { toast("Model jobs updated"); onChange(); },
    onError: (e) => toast((e as Error).message, "bad"),
  });
  return (
    <div className="mt-3 space-y-3">
      {models.map((m) => (
        <fieldset key={m.model} className="rounded-lg border border-line p-3">
          <legend className="px-1 font-mono text-xs text-ink">{m.model}{m.roles_custom ? " · customised" : ""}</legend>
          {m.pause_reason && <PausedNote m={m} onChange={onChange} toast={toast} />}
          <div className="flex flex-wrap gap-x-4 gap-y-1">
            {Object.entries(ROLE_LABEL).map(([r, label]) => (
              <label key={r} className="flex items-center gap-1.5 text-xs">
                <input type="checkbox" checked={m.roles.includes(r)} disabled={save.isPending}
                  onChange={(e) => save.mutate({ m, roles: e.target.checked ? [...m.roles, r] : m.roles.filter((x) => x !== r) })} />{label}
              </label>
            ))}
          </div>
        </fieldset>
      ))}
      {supported.length > 0 && (
        <details className="text-xs text-muted"><summary className="cursor-pointer">Models your keys can access ({supported.length}, from the last test)</summary>
          <p className="mt-2 font-mono leading-5">{supported.join(" · ")}</p></details>
      )}
    </div>
  );
}

function AddProvider({ onDone }: { onDone: () => void }) {
  const toast = useToast();
  const [open, setOpen] = useState(false);
  const [f, setF] = useState({ name: "", base_url: "https://", model: "", roles: ["critic"] as string[], commercial: false });
  const add = useMutation({
    mutationFn: () => callWorker("/api/providers/add", { name: f.name, base_url: f.base_url, commercial_use_ok: f.commercial,
      models: [{ id: f.model, roles: f.roles }] }),
    onSuccess: () => { toast("Provider added (switched off). Add a key, test it, then switch it on."); setOpen(false); onDone(); },
    onError: (e) => toast((e as Error).message, "bad"),
  });
  return (
    <section className="mt-8 rounded-xl border border-dashed border-line" aria-labelledby="addprov-title">
      <button className="flex w-full items-center gap-2 px-4 py-3 text-left" onClick={() => setOpen(!open)} aria-expanded={open}>
        <Plus size={16} aria-hidden /><h2 id="addprov-title" className="text-sm font-semibold text-ink">Add another provider (OpenAI-compatible API)</h2>
        <ChevronDown size={14} className={`ml-auto ${open ? "rotate-180" : ""}`} aria-hidden />
      </button>
      {open && (
        <form className="grid gap-3 border-t border-line p-4 sm:grid-cols-2" onSubmit={(e) => { e.preventDefault(); add.mutate(); }}>
          <label className="text-sm">Short id<input className="field mt-1" required pattern="[a-z][a-z0-9_-]{1,31}" value={f.name} onChange={(e) => setF({ ...f, name: e.target.value.toLowerCase() })} placeholder="e.g. openai" /></label>
          <label className="text-sm">Base URL<input className="field mt-1" required type="url" value={f.base_url} onChange={(e) => setF({ ...f, base_url: e.target.value })} placeholder="https://api.example.com/v1" /></label>
          <label className="text-sm">First model id<input className="field mt-1" required value={f.model} onChange={(e) => setF({ ...f, model: e.target.value })} /></label>
          <fieldset className="text-sm"><legend>Jobs for this model</legend>
            <div className="mt-1 flex flex-wrap gap-x-3 gap-y-1">{Object.entries(ROLE_LABEL).map(([r, label]) => (
              <label key={r} className="flex items-center gap-1 text-xs"><input type="checkbox" checked={f.roles.includes(r)} onChange={(e) => setF({ ...f, roles: e.target.checked ? [...f.roles, r] : f.roles.filter((x) => x !== r) })} />{label}</label>))}</div>
          </fieldset>
          <label className="flex items-start gap-2 text-sm sm:col-span-2"><input type="checkbox" className="mt-1" checked={f.commercial} onChange={(e) => setF({ ...f, commercial: e.target.checked })} />
            <span>I've checked this provider's terms allow use for monetised content. Without this, the router never uses it. Paid providers cost money: set a monthly cap and prices on each key.</span></label>
          <div className="sm:col-span-2"><button className="btn-quiet" disabled={add.isPending || !workerUrl}>Add provider</button></div>
        </form>
      )}
    </section>
  );
}
