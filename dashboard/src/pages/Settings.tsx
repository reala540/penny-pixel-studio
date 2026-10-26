import { useFormDraft } from "../lib/formDraft";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { lazy, Suspense, useEffect, useState } from "react";
import { Link, NavLink, useNavigate, useParams, useSearchParams } from "react-router-dom";
import AutoPostToggle, { AutoFixAttempts, AutoReplaceSettings, AutoReviewLog } from "../components/AutoPostToggle";
import ClearButton from "../components/ClearButton";
import PostingSchedule from "../components/PostingSchedule";
import ThemeControl from "../components/ThemeControl";
import { useCleared, visibleAfterClear } from "../lib/clear";
import { STALE_HOURS, useKeyCheck, useReadiness } from "../lib/readiness";
import { SETTINGS_SECTIONS, type SettingsSection } from "../lib/routes";
import { ErrorNote, Loading, NotConfirmed, PageHeader, useToast } from "../components/ui";
import { cleanCategories, cleanRegions, DEFAULT_IDEA_CONFIG, SOURCES } from "../lib/ideas";
import { useIdeaRuns } from "../lib/ideasApi";
import type { IdeaGeneratorConfig } from "../lib/types";
import { must, runWorkflow, useAccounts, useSaveSetting, useSetting } from "../lib/api";
import { PLATFORM_NAME } from "../lib/format";
import { callWorker, supabase, workerUrl } from "../lib/supabase";
import { PauseButton } from "./Home";

const SetupPage = lazy(() => import("./Setup"));
const ApiManager = lazy(() => import("./ApiManager"));

const SECTION_BODY: Record<SettingsSection, () => JSX.Element> = {
  setup: () => <SetupPage />,
  accounts: () => <Accounts />,
  schedule: () => (
    <Section id="posting-schedule" title="Posting schedule" intro="Choose the days, times and number of posts per week for each account, or pause one without disconnecting it.">
      <PostingSchedule />
    </Section>
  ),
  automation: () => <Automation />,
  ideas: () => <IdeaGeneration />,
  ai: () => <><KeyCheckPanel /><div className="mt-10"><Writers /></div><div className="mt-10"><ApiManager /></div></>,
  voices: () => <Voices />,
  notifications: () => <Telegram />,
  budget: () => <Budget />,
  appearance: () => <><Appearance /><div className="mt-14"><Schedule /></div></>,
};

export default function SettingsPage() {
  const { section = "setup" } = useParams();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const toast = useToast();
  useEffect(() => {
    if (params.get("connected")) toast(`${PLATFORM_NAME[params.get("connected") as keyof typeof PLATFORM_NAME] ?? "Account"} connected`);
    if (params.get("connect_error")) toast(`Couldn't connect: ${params.get("connect_error")}`, "bad");
  }, []);
  const current = (SETTINGS_SECTIONS.find(([k]) => k === section) ?? SETTINGS_SECTIONS[0])[0];
  const Body = SECTION_BODY[current];
  return (
    <>
      <PageHeader title="Settings" intro="Connections, schedule, automation and house rules, one section at a time." />
      <div className="grid gap-6 lg:grid-cols-[220px_minmax(0,1fr)]">
        <nav aria-label="Settings sections" className="lg:sticky lg:top-4 lg:self-start">
          <label className="lg:hidden"><span className="sr-only">Settings section</span>
            <select aria-label="Settings section" className="field" value={current} onChange={(e) => navigate(`/settings/${e.target.value}`)}>
              {SETTINGS_SECTIONS.map(([k, label]) => <option key={k} value={k}>{label}</option>)}
            </select>
          </label>
          <ul className="hidden flex-col gap-0.5 lg:flex">
            {SETTINGS_SECTIONS.map(([k, label]) => (
              <li key={k}><NavLink to={`/settings/${k}`} className={({ isActive }) => `block rounded-lg px-3 py-1.5 text-sm ${isActive ? "bg-ink text-surface" : "text-muted hover:bg-sunken hover:text-ink"}`}>{label}</NavLink></li>
            ))}
          </ul>
        </nav>
        <div className="min-w-0"><Suspense fallback={<Loading label="Loading section" />}><Body /></Suspense></div>
      </div>
    </>
  );
}

/** Settings → AI services: when the keys were last checked, what passed, which jobs have no passing service, and Test again. */
function KeyCheckPanel() {
  const [params]=useSearchParams();
  const selectedId=params.get("job");
  const selected=useQuery({
    queryKey:["selected-key-check",selectedId],enabled:Boolean(selectedId),
    refetchInterval:(q)=>q.state.data && ["queued","running"].includes(q.state.data.status) ? 5000 : false,
    queryFn:async()=>await must(supabase.from("generation_jobs").select("id,status,progress,output,error_message").eq("id",selectedId!).eq("job_type","check_providers").maybeSingle()) as {status:string;progress?:{label?:string};output?:{ok?:number;checked?:number};error_message?:string}|null,
  });
  const toast = useToast();
  const check = useSetting<{ checked_at?: string; results?: { provider: string; status: string; note?: string; error?: string }[] } | null>("provider_check", null);
  const ready = useReadiness();
  const keyCheck = useKeyCheck();
  const results = check.data?.results ?? [];
  return (
    <Section id="key-check" title="AI key check" intro="One short test request for every model that's switched on, with the keys the studio really uses: built-in services, services you added, and keys saved here or in GitHub secrets.">
      {selectedId && (!selected.isSuccess ? <NotConfirmed q={selected} what="the selected AI test" /> : selected.data ? <p role="status" className="mb-3 rounded-lg bg-sunken p-3 text-sm">Selected test: {selected.data.status}{selected.data.progress?.label ? ` · ${selected.data.progress.label}` : ""}{selected.data.status === "completed" ? ` · ${selected.data.output?.ok ?? 0} of ${selected.data.output?.checked ?? 0} services passed` : ""}{selected.data.error_message ? ` · ${selected.data.error_message.slice(0,200)}` : ""}</p> : <p>This test is no longer available. The latest results are below.</p>)}
      <div className="max-w-3xl rounded-xl border border-line bg-surface p-4 text-sm">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <p>{ready.checkedAt ? <>Last checked {new Date(ready.checkedAt).toLocaleString()}{ready.stale && <span className="ml-1 font-medium text-alert">(older than {STALE_HOURS} hours: results may have changed)</span>}</> : check.isSuccess ? "Not checked yet." : check.isError ? "Couldn't load the last check." : "Loading the last check…"}</p>
          <button className="btn-primary" disabled={keyCheck.running || keyCheck.run.isPending}
            onClick={() => keyCheck.run.mutate(undefined, { onSuccess: () => toast("Testing the AI keys. Results appear here in a few minutes."), onError: (e) => toast((e as Error).message, "bad") })}>
            {keyCheck.running ? "Testing…" : "Test again"}</button>
        </div>
        {results.length > 0 && (
          <ul className="mt-3 grid gap-1 sm:grid-cols-2">
            {results.map((r) => (
              <li key={r.provider} className="flex items-start gap-2">
                <span className={`mt-1.5 h-2 w-2 shrink-0 rounded-full ${r.status === "ok" ? "bg-penny" : r.status === "no key" ? "bg-line" : "bg-alert"}`} aria-hidden />
                <span><span className="font-medium">{r.provider}</span>: <span className="text-muted">{r.status === "ok" ? r.note ?? "works" : r.status === "no key" ? "no key" : (r.error ?? "failed").slice(0, 160)}</span>
                  {r.status === "ok" && r.error && <span className="block text-xs text-alert">Not working: {r.error.slice(0, 200)}</span>}</span>
              </li>
            ))}
          </ul>
        )}
        {ready.uncoveredRoles.length > 0 && ready.checkedAt && (
          <p className="mt-3 rounded-lg bg-gold/15 px-3 py-2 text-ink">No service that passed the last check does these jobs: <strong>{ready.uncoveredRoles.join(", ")}</strong>.
            Tick them on a working model under <em>Models and the jobs they do</em> below, or a package may stop at that step.</p>
        )}
      </div>
    </Section>
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
    <Section id="appearance" title="Appearance" intro="Light, dark, or follow your device. Remembered on this device.">
      <ThemeControl />
    </Section>
  );
}

function useIdeaConfig(): [IdeaGeneratorConfig, (patch: Partial<IdeaGeneratorConfig>, msg?: string) => void, boolean, ReturnType<typeof useSetting<Partial<IdeaGeneratorConfig>>>] {
  const raw = useSetting<Partial<IdeaGeneratorConfig>>("idea_generator", {});
  const save = useSaveSetting();
  const toast = useToast();
  const cfg = { ...DEFAULT_IDEA_CONFIG, ...(raw.data ?? {}) };
  const update = (patch: Partial<IdeaGeneratorConfig>, msg = "Saved") =>
    save.mutate({ key: "idea_generator", value: patch, patch: true }, { onSuccess: () => toast(msg), onError: (e) => toast((e as Error).message, "bad") });
  return [cfg, update, raw.isLoading, raw];
}

const WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

function IdeaGeneration() {
  const [cfg, update, loading, cfgQuery] = useIdeaConfig();
  const [textDraft,setTextDraft,draft]=useFormDraft("idea-settings", {categories:cfg.categories.join(", "),regions:cfg.region === "global" ? "" : cfg.region.join(", "),audience:cfg.audience});
  const {categories,regions,audience}=textDraft;
  const setCategories=(categories:string)=>setTextDraft((v)=>({...v,categories}));
  const setRegions=(regions:string)=>setTextDraft((v)=>({...v,regions}));
  const setAudience=(audience:string)=>setTextDraft((v)=>({...v,audience}));
  if (loading) return <Section id="ideas" title="Idea generation"><Loading /></Section>;
  if (!cfgQuery.isSuccess) return <NotConfirmed q={cfgQuery} what="idea generation settings" />;
  return (
    <Section id="ideas" title="Idea generation" intro="What the AI Idea Generator researches and how it ranks ideas. Scoring weights are fixed: current trend evidence 70%, originality 10%, international relevance 10%, feasibility 5%, engagement 5%.">
      {draft.message && <p role="status" className="mb-3 text-sm text-muted">{draft.message} <button className="underline" onClick={draft.reset}>Discard text edits</button></p>}
      <div className="grid max-w-3xl gap-4 sm:grid-cols-2">
        <label className="text-sm"><span className="text-muted">Ideas per batch</span>
          <input className="field mt-1" type="number" min={1} max={30} defaultValue={cfg.count}
            onBlur={(e) => { const n = Math.min(30, Math.max(1, Number(e.target.value) || 10)); if (n !== cfg.count) update({ count: n }); }} /></label>
        <label className="text-sm"><span className="text-muted">Minimum score to keep (0–100)</span>
          <input className="field mt-1" type="number" min={0} max={100} defaultValue={cfg.min_score}
            onBlur={(e) => { const n = Math.min(100, Math.max(0, Number(e.target.value) || 0)); if (n !== cfg.min_score) update({ min_score: n }); }} /></label>
        <label className="text-sm sm:col-span-2"><span className="text-muted">Regions (country codes like US, GB; empty = each channel's target countries)</span>
          <input className="field mt-1" value={regions ?? (cfg.region === "global" ? "" : cfg.region.join(", "))} onChange={(e) => setRegions(e.target.value)}
            onBlur={() => !draft.conflict && JSON.stringify(cleanRegions(regions))!==JSON.stringify(cfg.region) && update({ region: cleanRegions(regions) })} placeholder="Each channel's target countries" /></label>
        <label className="text-sm sm:col-span-2"><span className="text-muted">Categories and industries (comma separated)</span>
          <input className="field mt-1" value={categories ?? cfg.categories.join(", ")} onChange={(e) => setCategories(e.target.value)}
            onBlur={() => !draft.conflict && JSON.stringify(cleanCategories(categories))!==JSON.stringify(cfg.categories) && update({ categories: cleanCategories(categories) })} placeholder="e.g. AI tools, personal finance, careers" /></label>
        <label className="text-sm sm:col-span-2"><span className="text-muted">Target audience (empty = each channel's audience)</span>
          <input className="field mt-1" maxLength={300} value={audience ?? cfg.audience} onChange={(e) => setAudience(e.target.value)}
            onBlur={() => !draft.conflict && audience.trim()!==cfg.audience && update({ audience: audience.trim() })} /></label>
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
  const [cfg, update, loading, cfgQuery] = useIdeaConfig();
  const runs = useIdeaRuns(5);
  const cleared = useCleared();
  const shownRuns = visibleAfterClear(runs.data ?? [], cleared.map, "idea_runs", (r) => r.started_at);
  if (loading) return <Section id="automation" title="Automation"><Loading /></Section>;
  if (!cfgQuery.isSuccess) return <NotConfirmed q={cfgQuery} what="automation settings" />;
  return (
    <Section id="automation" title="Automation" intro="Who approves publishing, the publishing pause, fix attempts and scheduled idea batches.">
      <div className="mb-6 flex max-w-3xl flex-wrap items-center justify-between gap-3 rounded-xl border border-line bg-surface p-4">
        <p className="text-sm">Publishing pause: stops all posting on every account. Making content keeps working.</p>
        <PauseButton />
      </div>
      <p className="mb-6 max-w-3xl text-sm text-muted">To run research, the weekly batch or due posts now, use <Link to="/activity#quick-actions" className="text-pixel underline">Activity → Quick actions</Link>.</p>
      <div className="mb-6 max-w-3xl rounded-xl border border-line bg-surface p-4">
        <AutoPostToggle />
        <p className="mt-3 text-xs leading-5 text-muted">OFF (default): every package waits for your approval, exactly as before. ON: packages that pass
          every check and a confident independent AI review are approved automatically and post at their scheduled times to your
          configured accounts. Anything else waits for you and is sent to Telegram. Also in Telegram: /autopost.</p>
        <AutoFixAttempts />
        <AutoReplaceSettings />
        <div className="mt-4 flex flex-wrap items-center justify-between gap-2">
          <h3 className="text-sm font-semibold text-ink">Recent automatic reviews</h3>
          <ClearButton title="Clear the review log?" done="Review log cleared" className="btn-quiet px-2.5 py-1 text-xs"
            body="This hides the automatic reviews listed now. Every decision stays in the audit log, and you can undo this."
            onClear={() => cleared.clear("review_log")} />
        </div>
        <AutoReviewLog />
      </div>
      <h3 className="mb-3 text-sm font-semibold text-ink">Idea batches</h3>
      <p className="mb-3 max-w-3xl text-sm text-muted">Generated ideas only go to the Idea Library; they never start production by themselves.</p>
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
      </div>
      <div className="mt-6 flex max-w-3xl flex-wrap items-center justify-between gap-2">
        <h3 className="text-sm font-semibold text-ink">Recent idea runs</h3>
        {shownRuns.length > 0 && <ClearButton title="Clear the idea run history?" done="Idea run history cleared" className="btn-quiet px-2.5 py-1 text-xs"
          body="This hides the runs listed here and in the Idea Library. The ideas themselves stay. You can undo this."
          onClear={() => cleared.clear("idea_runs")} />}
      </div>
      {runs.isLoading ? <Loading /> : runs.isError ? <NotConfirmed q={runs} what="recent idea runs" /> : shownRuns.length === 0 ? <p className="mt-1 text-sm text-muted">None yet.</p> : (
        <ul className="mt-2 max-w-3xl divide-y divide-line rounded-xl border border-line bg-surface text-sm">
          {shownRuns.map((r) => <li key={r.id} className="flex flex-wrap justify-between gap-2 px-4 py-2">
            <span>{new Date(r.started_at).toLocaleString()} · {r.trigger}</span>
            <span className="text-muted">{r.status} · {r.produced_count}/{r.requested_count} ideas</span></li>)}
        </ul>
      )}
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
      {accounts.isLoading ? <Loading /> : accounts.isError ? <NotConfirmed q={accounts} what="your accounts" /> : (
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
      {!workerUrl && <p className="mt-2 text-sm text-alert">Connecting needs the Worker. See Settings → Getting started.</p>}
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
    <Section id="writers" title="AI writers" intro="Free services only. If one is busy or out of free requests, the next one takes over automatically. A service is used only if it has a key (added below or saved as a GitHub secret).">
      <ErrorNote error={data.error} onRetry={() => data.refetch()} retrying={data.isFetching} />
      <div className="overflow-x-auto rounded-xl border border-line bg-surface">
        <table className="w-full min-w-[620px] text-left text-sm">
          <thead className="border-b border-line text-xs text-muted">
            <tr><th className="px-4 py-2.5 font-medium">Service</th><th className="px-3 py-2.5 font-medium">Used for</th><th className="px-3 py-2.5 font-medium">Today</th><th className="px-3 py-2.5 font-medium">Health</th><th className="px-3 py-2.5 font-medium">On</th></tr>
          </thead>
          <tbody className="divide-y divide-line">
            {(d?.providers ?? []).map((p) => {
              const roles = [...new Set(d!.models.filter((m) => m.provider === p.name && m.enabled).flatMap((m) => m.roles))];
              const today = d!.usage.filter((u) => u.provider === p.name);
              const resting = p.circuit_open_until && Date.parse(p.circuit_open_until) > Date.now();
              return (
                <tr key={p.name}>
                  <td className="px-4 py-2.5 font-medium">{PROVIDER_NAME[p.name] ?? p.name}{!p.commercial_use_ok && <span className="block text-xs font-normal text-alert">Not for monetized use</span>}</td>
                  <td className="px-3 py-2.5 text-xs text-muted">{roles.map((r) => r.replace(/_/g, " ")).join(", ")}</td>
                  <td className="px-3 py-2.5 tabular">{today.length} calls</td>
                  <td className="px-3 py-2.5 text-xs">{resting ? <span className="text-alert">Resting: {String(p.last_error ?? "").slice(0, 60)}</span> : p.last_success_at ? <span className="text-muted">Last success: {new Date(p.last_success_at).toLocaleString()}</span> : <span className="text-muted">Not used yet</span>}</td>
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
      {channels.isLoading ? <Loading /> : channels.isError ? <NotConfirmed q={channels} what="channel voices" /> : (
        <div className="grid gap-6 lg:grid-cols-2">
          {(channels.data ?? []).map((c) => <VoiceForm key={c.id} channel={c} onSaved={() => { qc.invalidateQueries({ queryKey: ["channels"] }); toast(`${c.display_name} voice saved`); }} />)}
        </div>
      )}
    </Section>
  );
}

function VoiceForm({ channel, onSaved }: { channel: any; onSaved: () => void }) {
  const [form, setForm, draft] = useFormDraft(`voice:${channel.id}`, { persona: channel.host_persona as string, rules: (channel.voice_profile?.style_rules ?? []).join("\n") as string, tone: (channel.voice_profile?.tone ?? []).join(", ") as string });
  const {persona, rules, tone} = form;
  const setPersona = (persona: string) => setForm((v) => ({...v, persona}));
  const setRules = (rules: string) => setForm((v) => ({...v, rules}));
  const setTone = (tone: string) => setForm((v) => ({...v, tone}));
  const save = useMutation({
    mutationFn: async () => must(supabase.from("channel_profiles").update({
      host_persona: persona,
      voice_profile: { ...channel.voice_profile, tone: tone.split(",").map((t) => t.trim()).filter(Boolean), style_rules: rules.split("\n").map((r) => r.trim()).filter(Boolean) },
    }).eq("id", channel.id).eq("host_persona",channel.host_persona).eq("voice_profile", JSON.stringify(channel.voice_profile)).select("id").single()),
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
      {draft.message && <p role="status" className="mt-2 text-sm text-muted">{draft.message} <button type="button" className="underline" onClick={draft.reset}>Discard edits</button></p>}
      <button className="btn-quiet mt-3" disabled={save.isPending || draft.conflict}>Save voice</button>
    </form>
  );
}

function Budget() {
  const b = useQuery({ queryKey: ["budget"], queryFn: async () => ((await must(supabase.from("budgets").select("*").eq("service", "x_api"))) as any[])[0] });
  if (!b.isSuccess) return <NotConfirmed q={b} what="the X budget" />;
  if (!b.data) return <p>The X budget is not configured. Complete Getting started before changing it.</p>;
  return <BudgetEditor budget={b.data} />;
}
function BudgetEditor({budget}: {budget: {monthly_cap_usd: number; enabled: boolean}}) {
  const qc = useQueryClient();
  const toast = useToast();
  const [cap, setCap, draft] = useFormDraft("budget:x",String(budget.monthly_cap_usd));
  const save = useMutation({
    mutationFn: async () => {
      if (!cap.trim() || !Number.isFinite(Number(cap)) || Number(cap) < 0 || Number(cap) > 1) throw new Error("Enter a monthly limit between $0 and $1.");
      return must(supabase.from("budgets").update({ monthly_cap_usd: Number(cap), enabled: true }).eq("service", "x_api").eq("monthly_cap_usd", budget.monthly_cap_usd).select("service").single());
    },
    onSuccess: () => { qc.invalidateQueries(); toast("Budget saved"); },
    onError: (e) => toast((e as Error).message, "bad"),
  });
  return (
    <Section id="budget" title="Budget" intro="X is the only paid service. The studio stops posting to X the moment this monthly limit would be passed. Also set a spending limit inside your X developer account.">
      <form className="flex max-w-sm items-end gap-2" onSubmit={(e) => { e.preventDefault(); save.mutate(); }}>
        <label className="flex-1 text-sm"><span className="text-muted">X monthly limit (USD, max 1.00)</span>
          <input className="field mt-1 tabular" type="number" min="0" max="1" step="0.05" value={cap} onChange={(e) => setCap(e.target.value)} /></label>
        <button className="btn-quiet" disabled={save.isPending || draft.conflict}>{save.isPending ? "Saving…" : "Save"}</button>
      </form>
      {draft.message && <p role="status" className="mt-2 text-sm text-muted">{draft.message} <button className="underline" onClick={draft.reset}>Discard edits</button></p>}
    </Section>
  );
}

const ZONES = ["Africa/Nairobi", "Africa/Lagos", "Africa/Johannesburg", "Europe/London", "America/New_York", "Asia/Dubai", "Asia/Kolkata", "UTC"];

function Schedule() {
  const timezone = useSetting<string>("timezone", "Africa/Nairobi");
  const tz = timezone.data;
  const save = useSaveSetting();
  const toast = useToast();
  return (
    <Section id="timezone" title="Timezone" intro="This changes displayed times and future planning. Existing posts keep their scheduled instant; use Posting schedule to deliberately move them.">
      {!timezone.isSuccess ? <NotConfirmed q={timezone} what="the timezone" /> : <>
      <label className="block max-w-sm text-sm"><span className="text-muted">Timezone</span>
        <select aria-label="Timezone" className="field mt-1" value={tz} onChange={(e) => save.mutate({ key: "timezone", value: e.target.value }, { onSuccess: () => toast("Timezone saved") })}>
          {[...new Set([tz!, ...ZONES])].map((z) => <option key={z}>{z}</option>)}
        </select>
      </label></>}
    </Section>
  );
}

function Telegram() {
  const linkedQ = useSetting<string | null>("telegram_chat_id", null);
  const linked = linkedQ.data;
  const toast = useToast();
  const [code, setCode] = useState<string | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const get = useMutation({
    mutationFn: () => callWorker<{ code: string; telegram?: { ok: boolean; problem?: string } }>("/api/telegram/link-code", {}),
    onSuccess: (d) => { setCode(d.code); setProblem(d.telegram && !d.telegram.ok ? d.telegram.problem ?? "The bot isn't connected." : null); },
    onError: (e) => toast((e as Error).message, "bad"),
  });
  return (
    <Section id="telegram" title="Notifications (Telegram, optional)" intro="Recommended, not required: get 'ready for review', 'posted' and problem alerts on your phone, and pause publishing from anywhere.">
      {linkedQ.isSuccess ? <p className="text-sm">{linked ? "Linked. Alerts go to your Telegram chat." : "Not linked yet."}</p>
        : <NotConfirmed q={linkedQ} what="whether Telegram is linked" />}
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
      <AlertPreference />
      <UndeliveredAlerts />
    </Section>
  );
}

/** Which alerts go to Telegram. Everything always stays in the app (Activity). */
function AlertPreference() {
  const pref = useSetting<"all" | "important">("telegram_alerts", "all");
  const save = useSaveSetting();
  const toast = useToast();
  if (!pref.isSuccess) return <div className="mt-4"><NotConfirmed q={pref} what="your alert preference" compact /></div>;
  return (
    <fieldset className="mt-5 max-w-2xl text-sm">
      <legend className="font-medium">Telegram alerts</legend>
      {([["all", "Everything", "Problems, things that need you, and routine updates (ideas ready, posted, tests finished, and the evening heads-up that tomorrow's posts are ready)."],
        ["important", "Only what needs me", "Problems, packages waiting for your review, posts to check or post yourself, a heads-up when a post in the next 24 hours won't go out by itself, connection, key and budget problems. Routine updates stay in the app only."]] as const)
        .map(([v, label, help]) => (
          <label key={v} className="mt-2 flex items-start gap-2">
            <input type="radio" name="telegram_alerts" className="mt-1" checked={pref.data === v} disabled={save.isPending}
              onChange={() => save.mutate({ key: "telegram_alerts", value: v }, { onSuccess: () => toast("Alert preference saved. It applies to new alerts.") })} />
            <span><span className="font-medium">{label}</span><span className="block text-xs text-muted">{help}</span></span>
          </label>
        ))}
    </fieldset>
  );
}

/** Alerts from the last 7 days that didn't reach Telegram, and why (not set up, failed, unconfirmed, muted). */
function UndeliveredAlerts() {
  const q = useQuery({
    queryKey: ["undelivered-alerts"],
    refetchInterval: 60_000,
    queryFn: async () => (await must(supabase.from("notifications").select("id, title, error, created_at, link")
      .is("sent_at", null).not("error", "is", null).gte("created_at", new Date(Date.now() - 7 * 86_400_000).toISOString())
      .order("created_at", { ascending: false }).limit(10))) as { id: string; title: string; error: string; created_at: string; link: string | null }[],
  });
  if (!q.isSuccess) return <div className="mt-4"><NotConfirmed q={q} what="alert delivery" compact /></div>;
  if (!q.data.length) return <p className="mt-4 text-xs text-muted">Every alert in the last 7 days reached Telegram (or Telegram isn't set up yet).</p>;
  return (
    <div className="mt-5 max-w-3xl">
      <h3 className="text-sm font-medium">Alerts that didn't reach Telegram (last 7 days)</h3>
      <p className="text-xs text-muted">They're all still in Activity. "Unconfirmed" means Telegram didn't answer: the message may have arrived, and a retry can send it twice.</p>
      <ul className="mt-2 divide-y divide-line rounded-xl border border-line bg-surface text-sm">
        {q.data.map((n) => (
          <li key={n.id} className="px-3 py-2">
            <span className="font-medium">{n.title}</span>
            <span className="block text-xs text-muted">{new Date(n.created_at).toLocaleString()} · {n.error}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
