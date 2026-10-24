import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Activity, ArrowRight, BookOpenCheck, Bot, Check, ChevronRight, CircleAlert, Clock3,
  ExternalLink, FlaskConical, Pause, Play, RefreshCw, Search, Send, Settings2, ShieldCheck,
  Sparkles, Square, Wifi, WifiOff, Wrench, X,
} from "lucide-react";
import { FormEvent, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Empty, ErrorNote, StatusBadge, useToast } from "../components/ui";
import { must, queueJob, runWorkflow } from "../lib/api";
import { compact, embedTitle, jobLabel, relativeTime, workflowLabel } from "../lib/controlRoom";
import { supabase, workerUrl } from "../lib/supabase";

type ActivityRow = {
  id: number;
  provider: string;
  model: string | null;
  role: string | null;
  job_id: string | null;
  success: boolean;
  latency_ms: number | null;
  input_tokens: number;
  output_tokens: number;
  error: string | null;
  created_at: string;
};
type JobRow = {
  id: string;
  job_type: string;
  status: string;
  attempts: number;
  error_message: string | null;
  requested_by: string;
  created_at: string;
  updated_at: string;
  // Many-to-one embeds come back as one object; untyped clients describe them as a list. Accept both.
  content_projects?: { title: string } | { title: string }[] | null;
};
type ProviderRow = {
  name: string;
  enabled: boolean;
  last_success_at: string | null;
  last_error: string | null;
  circuit_open_until: string | null;
};
type ModelRow = { provider: string; model: string; roles: string[]; enabled: boolean };
type AccountRow = { id: string; label: string; oauth_connections?: { status: string }[] | null };
type Filter = "all" | "research" | "writing" | "review";

const ROLE_GROUP: Record<string, Exclude<Filter, "all">> = {
  research_summarizer: "research", brainstormer: "research",
  scriptwriter: "writing", voice_editor: "writing", repurposer: "writing",
  claim_checker: "review", critic: "review", angle_selector: "review",
};
const ROLE_LABEL: Record<string, string> = {
  research_summarizer: "Evidence scout", brainstormer: "Idea council", scriptwriter: "Scriptwriter",
  voice_editor: "Voice editor", repurposer: "Distribution editor", claim_checker: "Claim checker",
  critic: "Creative critic", angle_selector: "Hook selector", test: "Connection test",
};
const STAGES = [
  { id: "research", label: "Research", roles: ["research_summarizer", "brainstormer"], icon: Search },
  { id: "writing", label: "Create", roles: ["scriptwriter", "repurposer", "voice_editor"], icon: Sparkles },
  { id: "review", label: "Challenge", roles: ["claim_checker", "critic", "angle_selector"], icon: ShieldCheck },
] as const;
const PROVIDER_NAME: Record<string, string> = {
  gemini: "Gemini", groq: "Groq", nvidia: "NVIDIA", mistral: "Mistral", cloudflare: "Cloudflare",
  openrouter: "OpenRouter", aion: "Aion", ollama: "Ollama", zai: "Z AI", cerebras: "Cerebras",
  sambanova: "SambaNova", llm7: "LLM7", ovh: "OVHcloud", github_actions: "Runner",
};
const DEMO_ACTIVITY: ActivityRow[] = [
  { id: 6, provider: "openrouter", model: "nvidia/nemotron-3-ultra-550b-a55b:free", role: "critic", job_id: "demo-job", success: true, latency_ms: 1820, input_tokens: 3210, output_tokens: 680, error: null, created_at: new Date(Date.now() - 18_000).toISOString() },
  { id: 5, provider: "groq", model: "openai/gpt-oss-120b", role: "claim_checker", job_id: "demo-job", success: true, latency_ms: 940, input_tokens: 4100, output_tokens: 820, error: null, created_at: new Date(Date.now() - 42_000).toISOString() },
  { id: 4, provider: "nvidia", model: "z-ai/glm-5.3", role: "voice_editor", job_id: "demo-job", success: true, latency_ms: 2380, input_tokens: 2800, output_tokens: 1740, error: null, created_at: new Date(Date.now() - 71_000).toISOString() },
  { id: 3, provider: "gemini", model: "gemini-3.8-flash", role: "scriptwriter", job_id: "demo-job", success: true, latency_ms: 1240, input_tokens: 3500, output_tokens: 4100, error: null, created_at: new Date(Date.now() - 108_000).toISOString() },
  { id: 2, provider: "gemini", model: "gemini-3.8-flash", role: "brainstormer", job_id: "demo-research", success: true, latency_ms: 1980, input_tokens: 5200, output_tokens: 930, error: null, created_at: new Date(Date.now() - 162_000).toISOString() },
  { id: 1, provider: "cloudflare", model: "@cf/meta/llama-3.3-70b-instruct-fp8-fast", role: "research_summarizer", job_id: "demo-research", success: true, latency_ms: 1530, input_tokens: 6100, output_tokens: 1120, error: null, created_at: new Date(Date.now() - 201_000).toISOString() },
];
const DEMO_JOBS: JobRow[] = [
  { id: "demo-job", job_type: "script", status: "running", attempts: 1, error_message: null, requested_by: "system", created_at: new Date(Date.now() - 240_000).toISOString(), updated_at: new Date().toISOString(), content_projects: { title: "What actually changes when an AI agent can use a browser?" } },
  { id: "demo-research", job_type: "run_research", status: "completed", attempts: 1, error_message: null, requested_by: "owner", created_at: new Date(Date.now() - 400_000).toISOString(), updated_at: new Date(Date.now() - 190_000).toISOString(), content_projects: null },
];
const DEMO_PROVIDERS: ProviderRow[] = ["gemini", "groq", "nvidia", "cloudflare", "openrouter"].map((name) => ({ name, enabled: true, last_success_at: new Date().toISOString(), last_error: null, circuit_open_until: null }));
const DEMO_MODELS: ModelRow[] = [
  { provider: "gemini", model: "gemini-3.8-flash", roles: ["brainstormer", "scriptwriter"], enabled: true },
  { provider: "groq", model: "openai/gpt-oss-120b", roles: ["claim_checker"], enabled: true },
  { provider: "nvidia", model: "z-ai/glm-5.3", roles: ["voice_editor"], enabled: true },
  { provider: "cloudflare", model: "@cf/meta/llama-3.3-70b-instruct-fp8-fast", roles: ["research_summarizer"], enabled: true },
  { provider: "openrouter", model: "nvidia/nemotron-3-ultra-550b-a55b:free", roles: ["critic"], enabled: true },
];

export default function ControlRoom({ demo = false }: { demo?: boolean }) {
  const qc = useQueryClient();
  const toast = useToast();
  const [filter, setFilter] = useState<Filter>("all");
  const [polling, setPolling] = useState(true);
  const [activityOverride, setActivityOverride] = useState<ActivityRow[]>([]);
  const [objective, setObjective] = useState("");
  const [channel, setChannel] = useState("all");
  const [models, setModels] = useState(3);
  const [missionType, setMissionType] = useState<"research" | "production">("research");

  const activityQuery = useQuery({
    queryKey: ["control-activity"],
    enabled: !demo,
    refetchInterval: polling ? 5000 : false,
    queryFn: async () => (await must(supabase.from("provider_usage").select("id, provider, model, role, job_id, success, latency_ms, input_tokens, output_tokens, error, created_at").eq("service", "llm").order("created_at", { ascending: false }).limit(100))) as ActivityRow[],
  });
  const jobsQuery = useQuery({
    queryKey: ["control-jobs"],
    enabled: !demo,
    refetchInterval: polling ? 5000 : false,
    queryFn: async () => (await must(supabase.from("generation_jobs").select("id, job_type, status, attempts, error_message, requested_by, created_at, updated_at, content_projects(title)").order("updated_at", { ascending: false }).limit(40))) as unknown as JobRow[],
  });
  const providersQuery = useQuery({
    queryKey: ["control-providers"],
    enabled: !demo,
    refetchInterval: polling ? 15_000 : false,
    queryFn: async () => {
      const [providers, modelRows, accounts] = await Promise.all([
        must(supabase.from("ai_providers").select("name, enabled, last_success_at, last_error, circuit_open_until").order("name")),
        must(supabase.from("ai_model_configs").select("provider, model, roles, enabled").order("provider")),
        must(supabase.from("social_accounts").select("id, label, oauth_connections(status)").order("label")),
      ]);
      return { providers: providers as ProviderRow[], models: modelRows as ModelRow[], accounts: accounts as AccountRow[] };
    },
  });

  const activity = demo ? [...activityOverride, ...DEMO_ACTIVITY] : activityQuery.data ?? [];
  const jobs = demo ? DEMO_JOBS : jobsQuery.data ?? [];
  const providers = demo ? DEMO_PROVIDERS : providersQuery.data?.providers ?? [];
  const modelRows = demo ? DEMO_MODELS : providersQuery.data?.models ?? [];
  const accounts = demo ? [] : providersQuery.data?.accounts ?? [];
  const running = jobs.filter((j) => ["running", "queued", "retrying"].includes(j.status));
  const failed = jobs.filter((j) => ["failed", "blocked", "needs_review"].includes(j.status));
  const activeProviders = new Set(activity.filter((a) => Date.now() - Date.parse(a.created_at) < 90_000).map((a) => a.provider));
  const filtered = activity.filter((a) => filter === "all" || ROLE_GROUP[a.role ?? ""] === filter);
  const connected = accounts.filter((a) => a.oauth_connections?.[0]?.status === "connected").length;
  const lastUpdate = activity[0]?.created_at;

  const refresh = () => {
    qc.invalidateQueries({ queryKey: ["control-activity"] });
    qc.invalidateQueries({ queryKey: ["control-jobs"] });
    qc.invalidateQueries({ queryKey: ["control-providers"] });
  };
  const quickRun = useMutation({
    mutationFn: async (workflow: "research" | "produce" | "publish") => {
      if (demo) return;
      await runWorkflow(workflow);
    },
    onSuccess: (_d, workflow) => {
      toast(demo ? "Demo only — no workflow was started." : `${workflowLabel(workflow)} started. Watch the activity feed for live progress.`);
      if (!demo) window.setTimeout(refresh, 1200);
    },
    onError: (e) => toast((e as Error).message, "bad"),
  });
  const mission = useMutation({
    mutationFn: async () => {
      if (demo) return;
      await queueJob(missionType === "production" ? "run_mission" : "run_research", {
        input: { brief: objective.trim(), channel: channel === "all" ? null : channel, models },
      });
    },
    onSuccess: () => {
      if (demo) {
        const row: ActivityRow = { id: Date.now(), provider: "github_actions", model: null, role: "test", job_id: "demo-new", success: true, latency_ms: 0, input_tokens: 0, output_tokens: 0, error: null, created_at: new Date().toISOString() };
        setActivityOverride((rows) => [row, ...rows]);
        toast("Demo mission created locally — nothing was sent or saved.");
      } else {
        toast("Mission queued. The Worker will dispatch it shortly.");
        setObjective("");
        refresh();
      }
    },
    onError: (e) => toast((e as Error).message, "bad"),
  });
  const cancel = useMutation({
    mutationFn: async (id: string) => must(supabase.from("generation_jobs").update({ status: "cancelled" }).eq("id", id).eq("status", "queued")),
    onSuccess: () => { toast("Queued job cancelled"); refresh(); },
    onError: (e) => toast((e as Error).message, "bad"),
  });

  function submitMission(e: FormEvent) {
    e.preventDefault();
    if (objective.trim().length < 12) {
      toast("Give the team a little more direction (at least 12 characters).", "bad");
      return;
    }
    mission.mutate();
  }

  return (
    <div className="control-room -mx-4 -mb-28 -mt-6 min-h-[calc(100dvh-3rem)] px-4 pb-36 pt-5 sm:-mx-6 sm:px-6 md:-mb-12 md:pb-16">
      <header className="cr-header">
        <div>
          <div className="cr-kicker"><span className={`cr-live-dot ${running.length ? "is-active" : ""}`} />{demo ? "INTERACTIVE DEMO" : running.length ? "STUDIO ACTIVE" : "STUDIO READY"}</div>
          <h1 className="mt-2 font-display text-3xl font-semibold tracking-tight sm:text-4xl">Mission Control</h1>
          <p className="mt-2 max-w-2xl text-sm leading-6 text-[color:var(--cr-muted)]">{demo ? "Explore the operator workflow with clearly labelled sample activity. Nothing here contacts a provider or changes your studio." : "Watch independent models research, challenge and refine the work. Every event below comes from a real engine call."}</p>
        </div>
        <div className="cr-header-meta">
          <Clock />
          <span>{running.length} active · {failed.length} need attention</span>
          <div className="flex gap-2">
            <button className="cr-button" onClick={() => setPolling(!polling)} aria-label={polling ? "Pause activity refresh" : "Resume activity refresh"}>{polling ? <Pause size={14} /> : <Play size={14} />}{polling ? "Pause feed" : "Resume feed"}</button>
            <button className="cr-button" onClick={refresh} disabled={demo} aria-label="Refresh activity"><RefreshCw size={14} />Refresh</button>
          </div>
        </div>
      </header>

      {demo && <div className="mb-4 flex items-center gap-2 border border-[color:var(--cr-line-strong)] bg-[color:var(--cr-hover)] px-4 py-3 text-sm text-[color:var(--cr-ink)]"><FlaskConical size={16} className="text-[color:var(--cr-accent)]" />Sample data for interface evaluation. No accounts are contacted and no changes are saved.</div>}
      <ErrorNote error={activityQuery.error || jobsQuery.error || providersQuery.error} />

      <form className="cr-composer" onSubmit={submitMission}>
        <div className="flex items-start gap-3">
          <Wrench size={18} className="mt-1 shrink-0 text-[color:var(--cr-accent)]" />
          <div>
            <h2 className="text-sm font-semibold text-[color:var(--cr-ink)]">Direct the studio</h2>
            <p className="mt-1 text-xs leading-5 text-[color:var(--cr-muted)]">Give the council an objective. It will use configured sources and evidence checks; production still requires your approval.</p>
          </div>
        </div>
        <label className="mt-4 block">
          <span className="sr-only">Mission objective</span>
          <textarea className="cr-input min-h-20 resize-y" value={objective} maxLength={2000} onChange={(e) => setObjective(e.target.value)} placeholder="Example: Find three practical AI workflows for small businesses, compare the trade-offs, and challenge the strongest ideas." />
        </label>
        <div className="mt-3 flex flex-wrap items-end gap-3">
          <label className="cr-field"><span>Channel</span><select className="cr-input" value={channel} onChange={(e) => setChannel(e.target.value)}><option value="all">Both channels</option><option value="ai">Pixel · AI</option><option value="money">Penny · Money</option></select></label>
          <label className="cr-field"><span>Council depth</span><select className="cr-input" value={models} onChange={(e) => setModels(Number(e.target.value))}><option value={2}>Focused · 2 models</option><option value={3}>Balanced · 3 models</option><option value={5}>Wide · 5 models</option></select></label>
          <label className="cr-field"><span>Outcome</span><select className="cr-input" value={missionType} onChange={(e) => setMissionType(e.target.value as "research" | "production")}><option value="research">Research & ideas</option><option value="production">Research + review package</option></select></label>
          <button className="cr-primary ml-auto" disabled={mission.isPending || objective.trim().length < 12}><Send size={15} />{mission.isPending ? "Queueing…" : "Launch mission"}</button>
        </div>
      </form>

      <div className="mt-4 grid gap-4 xl:grid-cols-[238px_minmax(0,1fr)_310px]">
        <aside className="cr-panel" aria-labelledby="council-title">
          <PanelTitle id="council-title" icon={Bot} title="Model council" meta={`${providers.filter((p) => p.enabled).length} enabled`} />
          <ul className="divide-y divide-[color:var(--cr-line)]">
            {providers.filter((p) => p.enabled).map((p) => {
              const resting = Boolean(p.circuit_open_until && Date.parse(p.circuit_open_until) > Date.now());
              const live = activeProviders.has(p.name);
              const roles = [...new Set(modelRows.filter((m) => m.provider === p.name && m.enabled).flatMap((m) => m.roles))];
              return <li key={p.name} className="px-4 py-3">
                <div className="flex items-center gap-2"><span className={`cr-status-dot ${resting ? "warn" : live ? "live" : ""}`} /><span className="text-sm font-medium text-[color:var(--cr-ink)]">{PROVIDER_NAME[p.name] ?? p.name}</span><span className="ml-auto text-xs uppercase tracking-wider text-[color:var(--cr-faint)]">{resting ? "resting" : live ? "working" : "ready"}</span></div>
                <p className="mt-1.5 line-clamp-2 text-xs leading-4 text-[color:var(--cr-muted)]">{roles.map((r) => ROLE_LABEL[r] ?? r.replace(/_/g, " ")).join(" · ") || "Available for routing"}</p>
              </li>;
            })}
          </ul>
          {!providers.some((p) => p.enabled) && <div className="p-4 text-sm text-[color:var(--cr-muted)]">No providers enabled yet. Add keys and enable writers in Settings.</div>}
          <Link to="/settings#writers" className="cr-panel-link">Manage model roles <ChevronRight size={14} /></Link>
        </aside>

        <section className="min-w-0 space-y-4" aria-label="Agent activity">
          <div className="cr-panel overflow-hidden">
            <PanelTitle id="handoffs-title" icon={Activity} title="Live handoffs" meta={lastUpdate ? `Last event ${relativeTime(lastUpdate)}` : "Awaiting first run"} />
            <div className="cr-handoffs">
              {STAGES.map((stage, index) => {
                const latest = activity.find((a) => stage.roles.includes(a.role as never));
                const Icon = stage.icon;
                return <div className="contents" key={stage.id}>
                  <div className={`cr-stage ${latest && activeProviders.has(latest.provider) ? "active" : ""}`}>
                    <Icon size={16} /><span>{stage.label}</span>
                    <strong>{latest ? PROVIDER_NAME[latest.provider] ?? latest.provider : "Standby"}</strong>
                    <small>{latest ? ROLE_LABEL[latest.role ?? ""] ?? latest.role : "No calls yet"}</small>
                  </div>
                  {index < STAGES.length - 1 && <ArrowRight className="cr-handoff-arrow" size={17} aria-hidden />}
                </div>;
              })}
            </div>
          </div>

          <div className="cr-panel">
            <div className="flex flex-wrap items-center justify-between gap-3 border-b border-[color:var(--cr-line)] px-4 py-3">
              <PanelTitle id="stream-title" icon={Wifi} title="Reasoning trail" meta={`${filtered.length} events`} />
              <div className="flex gap-1" role="group" aria-label="Filter activity">
                {(["all", "research", "writing", "review"] as Filter[]).map((f) => <button key={f} onClick={() => setFilter(f)} aria-pressed={filter === f} className={`cr-filter ${filter === f ? "selected" : ""}`}>{f === "all" ? "All" : f === "writing" ? "Create" : f === "review" ? "Challenge" : "Research"}</button>)}
              </div>
            </div>
            {activityQuery.isLoading && !demo ? <div className="p-5 text-sm text-[color:var(--cr-muted)]">Loading engine activity…</div> : filtered.length === 0 ? (
              <div className="p-5"><Empty title="No model calls in this view">Run research or launch a mission above. New calls appear here automatically.</Empty></div>
            ) : <ol className="divide-y divide-[color:var(--cr-line)]">
              {filtered.slice(0, 40).map((a) => <ActivityItem key={a.id} row={a} />)}
            </ol>}
          </div>
        </section>

        <aside className="min-w-0 space-y-4">
          <section className="cr-panel" aria-labelledby="jobs-title">
            <PanelTitle id="jobs-title" icon={Clock3} title="Run queue" meta={`${jobs.length} recent`} />
            {jobs.length === 0 ? <p className="p-4 text-sm text-[color:var(--cr-muted)]">No jobs yet. Your first mission will appear here.</p> : <ul className="divide-y divide-[color:var(--cr-line)]">
              {jobs.slice(0, 6).map((j) => <li key={j.id} className="px-4 py-3">
                <div className="flex items-center gap-2"><span className="text-xs font-medium text-[color:var(--cr-ink)]">{jobLabel(j.job_type)}</span><span className="ml-auto"><StatusBadge status={j.status} /></span></div>
                <p className="mt-1 line-clamp-2 text-xs leading-4 text-[color:var(--cr-muted)]">{embedTitle(j.content_projects) ?? (j.requested_by === "owner" ? "Owner-directed run" : "Automated studio run")}</p>
                {j.error_message && <p className="mt-1 text-xs text-[color:var(--cr-bad)]">{j.error_message.slice(0, 140)}</p>}
                <div className="mt-2 flex items-center text-xs text-[color:var(--cr-faint)]"><span>{relativeTime(j.updated_at)}</span><span className="ml-2">attempt {j.attempts}</span>{j.status === "queued" && !demo && <button className="ml-auto inline-flex items-center gap-1 text-[color:var(--cr-warn)] hover:text-[color:var(--cr-warn-hover)]" onClick={() => cancel.mutate(j.id)}><X size={12} />Cancel</button>}</div>
              </li>)}
            </ul>}
          </section>

          <section className="cr-panel" aria-labelledby="actions-title">
            <PanelTitle id="actions-title" icon={Square} title="Operator actions" />
            <div className="grid gap-2 p-3">
              <button className="cr-action" onClick={() => quickRun.mutate("research")} disabled={quickRun.isPending}><Search size={15} /><span><strong>Research this week</strong><small>Collect sources and pitch ideas</small></span><ChevronRight size={14} /></button>
              <button className="cr-action" onClick={() => quickRun.mutate("produce")} disabled={quickRun.isPending}><Sparkles size={15} /><span><strong>Build review packages</strong><small>Scripts, checks, previews, schedule</small></span><ChevronRight size={14} /></button>
              <button className="cr-action" onClick={() => quickRun.mutate("publish")} disabled={quickRun.isPending}><BookOpenCheck size={15} /><span><strong>Publish approved & due</strong><small>Never touches unapproved work</small></span><ChevronRight size={14} /></button>
            </div>
          </section>

          <section className="cr-panel" aria-labelledby="readiness-title">
            <PanelTitle id="readiness-title" icon={Settings2} title="Readiness" />
            <dl className="space-y-3 px-4 py-4 text-xs">
              <ReadinessRow ok={connected > 0 || demo} label="Social accounts" value={demo ? "Sample only" : `${connected} of ${accounts.length} connected`} />
              <ReadinessRow ok={providers.some((p) => p.enabled)} label="Model routing" value={`${providers.filter((p) => p.enabled).length} providers enabled`} />
              <ReadinessRow ok={Boolean(workerUrl) || demo} label="Instant dispatch" value={workerUrl ? "Worker connected" : demo ? "Simulated" : "15-minute fallback"} />
              <ReadinessRow ok label="Publishing guard" value="Owner approval required" />
            </dl>
            {!demo && <Link to="/settings" className="cr-panel-link">Open setup & settings <ExternalLink size={13} /></Link>}
          </section>
        </aside>
      </div>
    </div>
  );
}

/** Ticks on its own so the rest of the page doesn't re-render every second. */
function Clock() {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const timer = window.setInterval(() => setNow(new Date()), 1000);
    return () => window.clearInterval(timer);
  }, []);
  return <span className="cr-clock">{now.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit", second: "2-digit" })}</span>;
}

function PanelTitle({ id, icon: Icon, title, meta }: { id: string; icon: typeof Activity; title: string; meta?: string }) {
  return <div className="flex items-center gap-2 px-4 py-3"><Icon size={15} className="text-[color:var(--cr-accent)]" /><h2 id={id} className="cr-panel-title">{title}</h2>{meta && <span className="ml-auto text-xs text-[color:var(--cr-faint)]">{meta}</span>}</div>;
}

function ActivityItem({ row }: { row: ActivityRow }) {
  const role = ROLE_LABEL[row.role ?? ""] ?? (row.role ?? "Model call").replace(/_/g, " ");
  return <li className="cr-activity-row">
    <span className={`cr-activity-marker ${row.success ? "" : "failed"}`}>{row.success ? <Check size={12} /> : <CircleAlert size={12} />}</span>
    <div className="min-w-0 flex-1">
      <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1"><span className="text-sm font-medium text-[color:var(--cr-ink)]">{role}</span><span className="text-xs text-[color:var(--cr-muted)]">{PROVIDER_NAME[row.provider] ?? row.provider}</span><span className="ml-auto text-xs text-[color:var(--cr-faint)]">{relativeTime(row.created_at)}</span></div>
      <p className="mt-1 truncate font-mono text-xs text-[color:var(--cr-faint)]" title={row.model ?? undefined}>{row.model ?? "workflow event"}</p>
      {!row.success && <p className="mt-1 text-xs text-[color:var(--cr-bad)]">{row.error ?? "Call failed; fallback routing may continue."}</p>}
    </div>
    <div className="w-20 shrink-0 text-right font-mono text-xs leading-5 text-[color:var(--cr-muted)]"><span className="block">{row.latency_ms == null ? "—" : `${(row.latency_ms / 1000).toFixed(1)}s`}</span><span>{compact(row.input_tokens + row.output_tokens)} tok</span></div>
  </li>;
}

function ReadinessRow({ ok, label, value }: { ok: boolean; label: string; value: string }) {
  return <div className="flex items-start gap-2"><dt className="flex min-w-0 flex-1 items-center gap-2 text-[color:var(--cr-muted)]">{ok ? <Check size={13} className="shrink-0 text-[color:var(--cr-ok)]" /> : <WifiOff size={13} className="shrink-0 text-[color:var(--cr-warn)]" />}{label}</dt><dd className="max-w-[52%] text-right text-[color:var(--cr-ink)]">{value}</dd></div>;
}

export function ControlRoomDemo() {
  return <div className="min-h-dvh bg-[color:var(--cr-bg)]"><div className="flex items-center justify-between border-b border-[color:var(--cr-line)] bg-[color:var(--cr-surface)] px-5 py-3 text-[color:var(--cr-ink)]"><div className="flex items-center gap-2"><Bot size={19} className="text-[color:var(--cr-accent)]" /><span className="whitespace-nowrap font-display font-semibold">Penny & Pixel Studio</span><span className="hidden text-xs text-[color:var(--cr-faint)] sm:inline">/ Mission Control</span></div><Link to="/" className="whitespace-nowrap text-xs text-[color:var(--cr-muted)] underline-offset-4 hover:text-[color:var(--cr-accent)] hover:underline">Studio sign in</Link></div><div className="mx-auto max-w-[1600px] p-4 sm:p-6"><ControlRoom demo /></div></div>;
}
