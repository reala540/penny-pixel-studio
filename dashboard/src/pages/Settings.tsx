import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { Link } from "react-router-dom";
import ThemeControl from "../components/ThemeControl";
import { ErrorNote, Loading, PageHeader, useToast } from "../components/ui";
import { cleanCategories, cleanRegions, DEFAULT_IDEA_CONFIG, SOURCES } from "../lib/ideas";
import { useIdeaRuns } from "../lib/ideasApi";
import type { IdeaGeneratorConfig } from "../lib/types";
import { must, runWorkflow, useAccounts, useSaveSetting, useSetting } from "../lib/api";
import { PLATFORM_NAME } from "../lib/format";
import { callWorker, supabase, workerUrl } from "../lib/supabase";

const SECTIONS = [
  ["appearance", "Appearance"],
  ["ideas", "Idea generation"],
  ["automation", "Automation"],
  ["providers", "AI providers"],
  ["accounts", "Accounts"],
  ["run", "Run now"],
  ["writers", "AI writers"],
  ["voices", "Channel voices"],
  ["budget", "Budget"],
  ["schedule", "Schedule"],
  ["telegram", "Telegram"],
] as const;

export default function SettingsPage() {
  const [params] = useSearchParams();
  const toast = useToast();
  useEffect(() => {
    if (params.get("connected")) toast(`${PLATFORM_NAME[params.get("connected") as keyof typeof PLATFORM_NAME] ?? "Account"} connected`);
    if (params.get("connect_error")) toast(`Couldn't connect: ${params.get("connect_error")}`, "bad");
  }, []);
  return (
    <>
      <PageHeader title="Settings" intro="Connect your accounts, choose which free AI services to use, and set the house rules." />
      <nav aria-label="Settings sections" className="mb-8 flex flex-wrap gap-x-4 gap-y-1 text-sm">
        {SECTIONS.map(([id, label]) => <a key={id} href={`#${id}`} className="text-muted underline-offset-4 hover:text-ink hover:underline">{label}</a>)}
      </nav>
      <div className="space-y-14">
        <Appearance />
        <IdeaGeneration />
        <Automation />
        <ProvidersLink />
        <Accounts />
        <RunNow />
        <Writers />
        <Voices />
        <Budget />
        <Schedule />
        <Telegram />
      </div>
    </>
  );
}

function Section({ id, title, intro, children }: { id: string; title: string; intro?: string; children: React.ReactNode }) {
  return (
    <section id={id} aria-labelledby={`${id}-title`} className="scroll-mt-6">
      <h2 id={`${id}-title`} className="section-title">{title}</h2>
      {intro && <p className="mt-1 max-w-2xl text-sm text-muted">{intro}</p>}
      <div className="mt-4">{children}</div>
    </section>
  );
}

function Appearance() {
  return (
    <Section id="appearance" title="Appearance" intro="Light, dark, or follow your device. Applies instantly on every page and is remembered on this device.">
      <ThemeControl />
    </Section>
  );
}

function useIdeaConfig(): [IdeaGeneratorConfig, (patch: Partial<IdeaGeneratorConfig>, msg?: string) => void, boolean] {
  const raw = useSetting<Partial<IdeaGeneratorConfig>>("idea_generator", {});
  const save = useSaveSetting();
  const toast = useToast();
  const cfg = { ...DEFAULT_IDEA_CONFIG, ...(raw.data ?? {}) };
  const update = (patch: Partial<IdeaGeneratorConfig>, msg = "Saved") =>
    save.mutate({ key: "idea_generator", value: { ...cfg, ...patch } }, { onSuccess: () => toast(msg), onError: (e) => toast((e as Error).message, "bad") });
  return [cfg, update, raw.isLoading];
}

const WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

function IdeaGeneration() {
  const [cfg, update, loading] = useIdeaConfig();
  const [categories, setCategories] = useState<string | null>(null);
  const [regions, setRegions] = useState<string | null>(null);
  const [audience, setAudience] = useState<string | null>(null);
  if (loading) return <Section id="ideas" title="Idea generation"><Loading /></Section>;
  return (
    <Section id="ideas" title="Idea generation" intro="What the AI Idea Generator researches and how it ranks ideas. Scoring weights are fixed: current trend evidence 70%, originality 10%, international relevance 10%, feasibility 5%, engagement 5%.">
      <div className="grid max-w-3xl gap-4 sm:grid-cols-2">
        <label className="text-sm"><span className="text-muted">Ideas per batch</span>
          <input className="field mt-1" type="number" min={1} max={30} defaultValue={cfg.count}
            onBlur={(e) => { const n = Math.min(30, Math.max(1, Number(e.target.value) || 10)); if (n !== cfg.count) update({ count: n }); }} /></label>
        <label className="text-sm"><span className="text-muted">Minimum score to keep (0–100)</span>
          <input className="field mt-1" type="number" min={0} max={100} defaultValue={cfg.min_score}
            onBlur={(e) => { const n = Math.min(100, Math.max(0, Number(e.target.value) || 0)); if (n !== cfg.min_score) update({ min_score: n }); }} /></label>
        <label className="text-sm sm:col-span-2"><span className="text-muted">Regions (country codes like US, KE, GB; empty = global)</span>
          <input className="field mt-1" value={regions ?? (cfg.region === "global" ? "" : cfg.region.join(", "))} onChange={(e) => setRegions(e.target.value)}
            onBlur={() => regions !== null && update({ region: cleanRegions(regions) })} placeholder="Global" /></label>
        <label className="text-sm sm:col-span-2"><span className="text-muted">Categories and industries (comma separated)</span>
          <input className="field mt-1" value={categories ?? cfg.categories.join(", ")} onChange={(e) => setCategories(e.target.value)}
            onBlur={() => categories !== null && update({ categories: cleanCategories(categories) })} placeholder="e.g. AI tools, personal finance, careers" /></label>
        <label className="text-sm sm:col-span-2"><span className="text-muted">Target audience (empty = each channel's audience)</span>
          <input className="field mt-1" maxLength={300} value={audience ?? cfg.audience} onChange={(e) => setAudience(e.target.value)}
            onBlur={() => audience !== null && update({ audience: audience.trim() })} /></label>
        <label className="text-sm"><span className="text-muted">Language</span>
          <select aria-label="Language" className="field mt-1" value={cfg.languages[0]} onChange={(e) => update({ languages: [e.target.value] })}>
            {[["en", "English"], ["fr", "French"], ["es", "Spanish"], ["pt", "Portuguese"], ["de", "German"], ["sw", "Swahili"]].map(([v, l]) => <option key={v} value={v}>{l}</option>)}
          </select></label>
        <fieldset className="text-sm"><legend className="text-muted">Channels</legend>
          <div className="mt-2 flex gap-4">{(["ai", "money"] as const).map((ch) => (
            <label key={ch} className="flex items-center gap-2"><input type="checkbox" checked={cfg.channels.includes(ch)}
              onChange={(e) => { const next = e.target.checked ? [...cfg.channels, ch] : cfg.channels.filter((x) => x !== ch); if (next.length) update({ channels: next }); }} />
              {ch === "ai" ? "Pixel · AI" : "Penny · Money"}</label>))}</div>
        </fieldset>
        <fieldset className="text-sm sm:col-span-2"><legend className="text-muted">Allowed research sources</legend>
          <div className="mt-2 grid gap-1 sm:grid-cols-2">{SOURCES.map((src) => (
            <label key={src.id} className="flex items-start gap-2"><input type="checkbox" className="mt-1" checked={cfg.sources.includes(src.id)}
              onChange={(e) => { const next = e.target.checked ? [...cfg.sources, src.id] : cfg.sources.filter((x) => x !== src.id); if (next.length) update({ sources: next }); }} />
              <span>{src.label}{src.needs && <span className="text-muted"> (needs {src.needs})</span>}</span></label>))}</div>
        </fieldset>
        <label className="flex items-center gap-2 text-sm sm:col-span-2"><input type="checkbox" checked={cfg.refresh_sources} onChange={(e) => update({ refresh_sources: e.target.checked })} />
          Fetch fresh research before each batch (recommended; otherwise only sources from the last 14 days already stored are used)</label>
      </div>
    </Section>
  );
}

function Automation() {
  const [cfg, update, loading] = useIdeaConfig();
  const runs = useIdeaRuns(5);
  if (loading) return <Section id="automation" title="Automation"><Loading /></Section>;
  return (
    <Section id="automation" title="Automation" intro="Scheduled idea batches. Generated ideas only go to the Idea Library: production and publishing always wait for your approval, and that can't be switched off.">
      <div className="grid max-w-3xl gap-4 sm:grid-cols-2">
        <label className="text-sm"><span className="text-muted">Generate ideas</span>
          <select aria-label="Generate ideas" className="field mt-1" value={cfg.frequency} onChange={(e) => update({ frequency: e.target.value as IdeaGeneratorConfig["frequency"] }, "Schedule saved")}>
            <option value="manual">Only when I press the button</option><option value="daily">Every day</option>
            <option value="weekly">Once a week</option><option value="custom">On the days I choose</option>
          </select></label>
        <label className="text-sm"><span className="text-muted">At (studio timezone)</span>
          <select aria-label="At (studio timezone)" className="field mt-1" value={cfg.hour} disabled={cfg.frequency === "manual"} onChange={(e) => update({ hour: Number(e.target.value) }, "Schedule saved")}>
            {Array.from({ length: 24 }, (_, h) => <option key={h} value={h}>{String(h).padStart(2, "0")}:00</option>)}
          </select></label>
        {(cfg.frequency === "weekly" || cfg.frequency === "custom") && (
          <fieldset className="text-sm sm:col-span-2"><legend className="text-muted">{cfg.frequency === "weekly" ? "Day" : "Days"}</legend>
            <div className="mt-2 flex flex-wrap gap-2">{WEEKDAYS.map((d, i) => {
              const on = cfg.weekdays.includes(i);
              return <button key={d} type="button" aria-pressed={on} className={`rounded-lg border px-3 py-1.5 text-sm ${on ? "border-ink bg-ink text-surface" : "border-line text-muted hover:text-ink"}`}
                onClick={() => {
                  const next = cfg.frequency === "weekly" ? [i] : on ? cfg.weekdays.filter((x) => x !== i) : [...cfg.weekdays, i].sort();
                  if (next.length) update({ weekdays: next }, "Schedule saved");
                }}>{d}</button>;
            })}</div>
          </fieldset>
        )}
        <label className="flex items-center gap-2 text-sm sm:col-span-2"><input type="checkbox" checked={cfg.notify} onChange={(e) => update({ notify: e.target.checked })} />
          Send me a Telegram message when a batch of ideas is ready</label>
        <p className="text-sm sm:col-span-2"><span className="font-medium text-ink">Approval:</span> <span className="text-muted">always required before production and publishing.</span></p>
      </div>
      <h3 className="mt-6 text-sm font-semibold text-ink">Recent idea runs</h3>
      {runs.isLoading ? <Loading /> : (runs.data ?? []).length === 0 ? <p className="mt-1 text-sm text-muted">None yet.</p> : (
        <ul className="mt-2 max-w-3xl divide-y divide-line rounded-xl border border-line bg-surface text-sm">
          {(runs.data ?? []).map((r) => <li key={r.id} className="flex flex-wrap justify-between gap-2 px-4 py-2">
            <span>{new Date(r.started_at).toLocaleString()} · {r.trigger}</span>
            <span className="text-muted">{r.status} · {r.produced_count}/{r.requested_count} ideas</span></li>)}
        </ul>
      )}
    </Section>
  );
}

function ProvidersLink() {
  return (
    <Section id="providers" title="AI providers" intro="Keys, model jobs, how keys share the work, limits, failover and monitoring.">
      <Link to="/api" className="btn-quiet">Open the AI API Manager</Link>
    </Section>
  );
}

function Accounts() {
  const accounts = useAccounts();
  const toast = useToast();
  const connect = useMutation({
    mutationFn: async (id: string) => (await callWorker<{ url: string }>("/api/oauth/start", { account_id: id })).url,
    onSuccess: (url) => { window.location.href = url; },
    onError: (e) => toast((e as Error).message, "bad"),
  });
  return (
    <Section id="accounts" title="Accounts" intro="Sign in once per account. Your login tokens are encrypted; the dashboard never sees them.">
      {accounts.isLoading ? <Loading /> : (
        <ul className="divide-y divide-line rounded-xl border border-line bg-surface">
          {(accounts.data ?? []).map((a) => {
            const c = a.oauth_connections;
            const status = c?.status ?? "disconnected";
            return (
              <li key={a.id} className="flex flex-wrap items-center gap-3 px-4 py-3">
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-medium">{a.label} <span className="font-normal text-muted">· {PLATFORM_NAME[a.platform]}{a.handle ? ` · ${a.handle}` : ""}</span></p>
                  {c?.last_error && <p className="text-xs text-alert">{c.last_error}</p>}
                </div>
                <ConnectionBadge status={status} />
                <button className="btn-quiet" onClick={() => connect.mutate(a.id)} disabled={connect.isPending || !workerUrl}>
                  {status === "connected" ? "Reconnect" : "Connect"}
                </button>
              </li>
            );
          })}
        </ul>
      )}
      {!workerUrl && <p className="mt-2 text-sm text-alert">Connecting needs the Worker. Add VITE_WORKER_URL (GUIDE.md, step 9).</p>}
    </Section>
  );
}

function ConnectionBadge({ status }: { status: string }) {
  const map: Record<string, [string, string]> = {
    connected: ["Connected", "bg-penny-soft text-penny"],
    needs_reauth: ["Reconnect needed", "bg-alert-soft text-alert"],
    expired: ["Reconnect needed", "bg-alert-soft text-alert"],
    error: ["Problem", "bg-alert-soft text-alert"],
  };
  const [text, cls] = map[status] ?? ["Not connected", "bg-sunken text-muted"];
  return <span className={`rounded-md px-2 py-0.5 text-xs font-medium ${cls}`}>{text}</span>;
}

const PROVIDER_NAME: Record<string, string> = {
  gemini: "Google Gemini", groq: "Groq", nvidia: "NVIDIA NIM", mistral: "Mistral", cloudflare: "Cloudflare Workers AI",
  openrouter: "OpenRouter", aion: "Aion Labs", ollama: "Ollama Cloud", zai: "Z AI (GLM)", cerebras: "Cerebras",
  sambanova: "SambaNova", llm7: "LLM7", ovh: "OVHcloud",
};

function RunNow() {
  const toast = useToast();
  const run = useMutation({
    mutationFn: (w: "research" | "produce" | "publish") => runWorkflow(w),
    onSuccess: (_d, w) => toast(`${w[0].toUpperCase()}${w.slice(1)} started. You'll get a Telegram message when it finishes.`),
    onError: (e) => toast((e as Error).message, "bad"),
  });
  return (
    <Section id="run" title="Run now" intro="These run automatically every week. Use them to start early or catch up.">
      <div className="flex flex-wrap gap-2">
        <button className="btn-quiet" onClick={() => run.mutate("research")} disabled={run.isPending}>Research ideas</button>
        <button className="btn-quiet" onClick={() => run.mutate("produce")} disabled={run.isPending}>Make this week's videos</button>
        <button className="btn-quiet" onClick={() => run.mutate("publish")} disabled={run.isPending}>Publish anything due</button>
      </div>
    </Section>
  );
}

function Writers() {
  const qc = useQueryClient();
  const toast = useToast();
  const data = useQuery({
    queryKey: ["providers"],
    queryFn: async () => {
      const [providers, models, usage] = await Promise.all([
        must(supabase.from("ai_providers").select("*").order("name")),
        must(supabase.from("ai_model_configs").select("provider, model, roles, daily_request_limit, enabled")),
        must(supabase.from("provider_usage").select("provider, requests, success").eq("service", "llm").eq("usage_date", new Date().toISOString().slice(0, 10)).limit(2000)),
      ]);
      return { providers: providers as any[], models: models as any[], usage: usage as any[] };
    },
  });
  const toggle = useMutation({
    mutationFn: async ({ name, enabled }: { name: string; enabled: boolean }) => must(supabase.from("ai_providers").update({ enabled }).eq("name", name)),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["providers"] }); toast("Saved"); },
  });
  if (data.isLoading) return <Section id="writers" title="AI writers"><Loading /></Section>;
  const d = data.data;
  return (
    <Section id="writers" title="AI writers" intro="Free services only. If one is busy or out of free requests, the next one takes over automatically. A service is used only if its key is saved in GitHub secrets.">
      <ErrorNote error={data.error} />
      <div className="overflow-x-auto rounded-xl border border-line bg-surface">
        <table className="w-full min-w-[620px] text-left text-sm">
          <thead className="border-b border-line text-xs text-muted">
            <tr><th className="px-4 py-2.5 font-medium">Service</th><th className="px-3 py-2.5 font-medium">Used for</th><th className="px-3 py-2.5 font-medium">Today</th><th className="px-3 py-2.5 font-medium">Health</th><th className="px-3 py-2.5 font-medium">On</th></tr>
          </thead>
          <tbody className="divide-y divide-line">
            {(d?.providers ?? []).map((p) => {
              const roles = [...new Set(d!.models.filter((m) => m.provider === p.name).flatMap((m) => m.roles))];
              const today = d!.usage.filter((u) => u.provider === p.name);
              const resting = p.circuit_open_until && Date.parse(p.circuit_open_until) > Date.now();
              return (
                <tr key={p.name}>
                  <td className="px-4 py-2.5 font-medium">{PROVIDER_NAME[p.name] ?? p.name}{!p.commercial_use_ok && <span className="block text-xs font-normal text-alert">Not for monetized use</span>}</td>
                  <td className="px-3 py-2.5 text-xs text-muted">{roles.map((r) => r.replace(/_/g, " ")).join(", ")}</td>
                  <td className="px-3 py-2.5 tabular">{today.length} calls</td>
                  <td className="px-3 py-2.5 text-xs">{resting ? <span className="text-alert">Resting: {String(p.last_error ?? "").slice(0, 60)}</span> : p.last_success_at ? <span className="text-ok">Working</span> : <span className="text-muted">Not used yet</span>}</td>
                  <td className="px-3 py-2.5">
                    <input type="checkbox" className="h-4 w-4 accent-current" checked={p.enabled} aria-label={`Use ${PROVIDER_NAME[p.name] ?? p.name}`} onChange={(e) => toggle.mutate({ name: p.name, enabled: e.target.checked })} />
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </Section>
  );
}

function Voices() {
  const qc = useQueryClient();
  const toast = useToast();
  const channels = useQuery({ queryKey: ["channels"], queryFn: async () => (await must(supabase.from("channel_profiles").select("*").order("slug"))) as any[] });
  return (
    <Section id="voices" title="Channel voices" intro="How Pixel and Penny sound. The writers follow these rules for every script.">
      {channels.isLoading ? <Loading /> : (
        <div className="grid gap-6 lg:grid-cols-2">
          {(channels.data ?? []).map((c) => <VoiceForm key={c.id} channel={c} onSaved={() => { qc.invalidateQueries({ queryKey: ["channels"] }); toast(`${c.display_name} voice saved`); }} />)}
        </div>
      )}
    </Section>
  );
}

function VoiceForm({ channel, onSaved }: { channel: any; onSaved: () => void }) {
  const [persona, setPersona] = useState<string>(channel.host_persona);
  const [rules, setRules] = useState<string>((channel.voice_profile?.style_rules ?? []).join("\n"));
  const [tone, setTone] = useState<string>((channel.voice_profile?.tone ?? []).join(", "));
  const save = useMutation({
    mutationFn: async () => must(supabase.from("channel_profiles").update({
      host_persona: persona,
      voice_profile: { ...channel.voice_profile, tone: tone.split(",").map((t) => t.trim()).filter(Boolean), style_rules: rules.split("\n").map((r) => r.trim()).filter(Boolean) },
    }).eq("id", channel.id)),
    onSuccess: onSaved,
  });
  return (
    <form className={`rounded-xl border-l-4 bg-surface p-4 ${channel.slug === "ai" ? "border-pixel" : "border-penny"}`} onSubmit={(e) => { e.preventDefault(); save.mutate(); }}>
      <h3 className="font-display text-lg font-semibold">{channel.display_name}</h3>
      <label className="mt-3 block text-sm"><span className="text-muted">Who the host is</span>
        <textarea className="field mt-1" rows={4} value={persona} onChange={(e) => setPersona(e.target.value)} /></label>
      <label className="mt-3 block text-sm"><span className="text-muted">Tone (comma separated)</span>
        <input className="field mt-1" value={tone} onChange={(e) => setTone(e.target.value)} /></label>
      <label className="mt-3 block text-sm"><span className="text-muted">Writing rules (one per line)</span>
        <textarea className="field mt-1" rows={5} value={rules} onChange={(e) => setRules(e.target.value)} /></label>
      <button className="btn-quiet mt-3" disabled={save.isPending}>Save voice</button>
    </form>
  );
}

function Budget() {
  const qc = useQueryClient();
  const toast = useToast();
  const b = useQuery({ queryKey: ["budget"], queryFn: async () => ((await must(supabase.from("budgets").select("*").eq("service", "x_api"))) as any[])[0] });
  const [cap, setCap] = useState<string>("");
  useEffect(() => { if (b.data) setCap(String(b.data.monthly_cap_usd)); }, [b.data?.monthly_cap_usd]);
  const save = useMutation({
    mutationFn: async () => must(supabase.from("budgets").update({ monthly_cap_usd: Number(cap), enabled: true }).eq("service", "x_api")),
    onSuccess: () => { qc.invalidateQueries(); toast("Budget saved"); },
    onError: () => toast("The X budget can be at most $1.00 a month.", "bad"),
  });
  return (
    <Section id="budget" title="Budget" intro="X is the only paid service. The studio stops posting to X the moment this monthly limit would be passed. Also set a spending limit inside your X developer account.">
      <form className="flex max-w-sm items-end gap-2" onSubmit={(e) => { e.preventDefault(); save.mutate(); }}>
        <label className="flex-1 text-sm"><span className="text-muted">X monthly limit (USD, max 1.00)</span>
          <input className="field mt-1 tabular" type="number" min="0" max="1" step="0.05" value={cap} onChange={(e) => setCap(e.target.value)} /></label>
        <button className="btn-quiet">Save</button>
      </form>
    </Section>
  );
}

const ZONES = ["Africa/Nairobi", "Africa/Lagos", "Africa/Johannesburg", "Europe/London", "America/New_York", "Asia/Dubai", "Asia/Kolkata", "UTC"];

function Schedule() {
  const tz = useSetting<string>("timezone", "Africa/Nairobi").data ?? "Africa/Nairobi";
  const save = useSaveSetting();
  const toast = useToast();
  return (
    <Section id="schedule" title="Schedule" intro="Posting times are shown and planned in this timezone. Change the posting days and times per account in config/accounts.yaml.">
      <label className="block max-w-sm text-sm"><span className="text-muted">Timezone</span>
        <select aria-label="Timezone" className="field mt-1" value={tz} onChange={(e) => save.mutate({ key: "timezone", value: e.target.value }, { onSuccess: () => toast("Timezone saved") })}>
          {[...new Set([tz, ...ZONES])].map((z) => <option key={z}>{z}</option>)}
        </select>
      </label>
    </Section>
  );
}

function Telegram() {
  const linked = useSetting<string | null>("telegram_chat_id", null).data;
  const toast = useToast();
  const [code, setCode] = useState<string | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const get = useMutation({
    mutationFn: () => callWorker<{ code: string; telegram?: { ok: boolean; problem?: string } }>("/api/telegram/link-code", {}),
    onSuccess: (d) => { setCode(d.code); setProblem(d.telegram && !d.telegram.ok ? d.telegram.problem ?? "The bot isn't connected." : null); },
    onError: (e) => toast((e as Error).message, "bad"),
  });
  return (
    <Section id="telegram" title="Telegram" intro="Get 'ready for review', 'posted' and problem alerts on your phone, and pause publishing from anywhere.">
      <p className="text-sm">{linked ? "Linked. Alerts go to your Telegram chat." : "Not linked yet."}</p>
      <button className="btn-quiet mt-3" onClick={() => get.mutate()} disabled={get.isPending || !workerUrl}>{linked ? "Link a different chat" : "Get a link code"}</button>
      {code && (
        <p className="mt-3 rounded-lg bg-sunken px-4 py-3 text-sm">
          Open your bot in Telegram and send: <code className="font-semibold">/link {code}</code>
        </p>
      )}
      {problem && (
        <p role="alert" className="mt-3 rounded-lg bg-alert-soft px-4 py-3 text-sm text-alert">
          The bot can't hear you yet. {problem}
        </p>
      )}
    </Section>
  );
}
