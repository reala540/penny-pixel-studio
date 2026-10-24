import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, CircleAlert, CircleCheck, CircleDashed, Copy, Eye, EyeOff, Info } from "lucide-react";
import { ReactNode, useState } from "react";
import { Link } from "react-router-dom";
import { ErrorNote, Loading, PageHeader, useToast } from "../components/ui";
import { useAccounts, useSaveSetting, useSetting } from "../lib/api";
import { PLATFORM_NAME } from "../lib/format";
import { callWorker, supabase, workerUrl } from "../lib/supabase";
import type { Platform } from "../lib/types";

type ValueState = { dashboard: boolean; hint: string | null; updated_at: string | null; readable: boolean; github: boolean | null };
type Status = { core: Record<string, { ok: boolean; detail: string }>; values: Record<string, ValueState>; core_names: string[]; engine_checked_at: string | null };
type Test = { ok: boolean | null; detail: string };

function useSetupStatus() {
  return useQuery({
    queryKey: ["setup-status"],
    enabled: Boolean(workerUrl),
    queryFn: () => callWorker<Status>("/api/setup/status", {}),
  });
}

export function useSetupProgress() {
  const status = useSetupStatus();
  const accounts = useAccounts();
  const chat = useSetting<string | null>("telegram_chat_id", null);
  const check = useSetting<{ results?: { status: string }[] } | null>("provider_check", null);
  const progress = useSetting<{ schedule_reviewed?: boolean }>("setup_progress", {});
  const firstVideo = useQuery({
    queryKey: ["setup-first-video"],
    queryFn: async () => {
      const { count, error } = await supabase.from("content_projects").select("id", { count: "exact", head: true });
      if (error) throw new Error(error.message);
      return (count ?? 0) > 0;
    },
  });
  const has = (n: string) => Boolean(status.data?.values[n]?.dashboard || status.data?.values[n]?.github);
  const connected = (p: Platform) => (accounts.data ?? []).filter((a) => a.platform === p).every((a) => a.oauth_connections?.status === "connected")
    && (accounts.data ?? []).some((a) => a.platform === p);
  const coreOk = status.data ? Object.values(status.data.core).every((c) => c.ok) : false;
  const steps: { id: string; title: string; done: boolean; optional?: boolean }[] = [
    { id: "basics", title: "The basics", done: coreOk },
    { id: "telegram", title: "Telegram", done: has("TELEGRAM_BOT_TOKEN") && Boolean(chat.data) },
    { id: "ai", title: "AI keys", done: (check.data?.results ?? []).some((r) => r.status === "ok") },
    { id: "youtube", title: "YouTube", done: connected("youtube") },
    { id: "facebook", title: "Facebook", done: connected("facebook") },
    { id: "tiktok", title: "TikTok", done: connected("tiktok") },
    { id: "x", title: "X", done: connected("x") },
    { id: "research", title: "Research keys", done: has("YOUTUBE_API_KEY"), optional: true },
    { id: "schedule", title: "Posting schedule", done: Boolean(progress.data?.schedule_reviewed) },
    { id: "first", title: "First video", done: Boolean(firstVideo.data) },
  ];
  const required = steps.filter((s) => !s.optional);
  return {
    steps, done: required.filter((s) => s.done).length, total: required.length,
    loading: status.isLoading || accounts.isLoading, status, accounts,
  };
}

export default function Setup() {
  const p = useSetupProgress();
  const pct = Math.round((p.done / p.total) * 100);
  if (!workerUrl) {
    return (
      <>
        <PageHeader title="Setup" intro="Everything the studio needs, step by step." />
        <p role="alert" className="rounded-xl bg-alert-soft px-4 py-3 text-sm text-alert">The dashboard doesn't know your Worker address yet, so Setup can't check or save anything.
          Add VITE_WORKER_URL in Vercel → your dashboard project → Settings → Environment Variables (GUIDE.md step 9), then redeploy.</p>
      </>
    );
  }
  return (
    <>
      <PageHeader title="Setup" intro="Each step tests itself and shows ✅ when it works. Paste values here instead of GitHub: they're encrypted on the server and the page only ever shows the last 4 characters. You can stop any time and continue later." />
      <div className="mb-8 max-w-4xl">
        <div className="flex items-baseline justify-between text-sm"><span className="font-medium">{p.done} of {p.total} steps done</span><span className="tabular text-muted">{pct}%</span></div>
        <div className="mt-2 h-2 overflow-hidden rounded-full bg-sunken" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={pct} aria-label="Setup progress">
          <span className="block h-full bg-penny transition-all" style={{ width: `${pct}%` }} />
        </div>
        <nav aria-label="Setup steps" className="mt-4 flex flex-wrap gap-2">
          {p.steps.map((s, i) => (
            <a key={s.id} href={`#${s.id}`} className={`inline-flex items-center gap-1.5 rounded-lg border px-2.5 py-1 text-xs ${s.done ? "border-penny/40 bg-penny-soft text-penny" : "border-line text-muted hover:text-ink"}`}>
              {s.done ? <Check size={12} aria-hidden /> : <span className="tabular">{i + 1}</span>}{s.title}{s.optional && " (optional)"}
              <span className="sr-only">{s.done ? "done" : "not done"}</span>
            </a>
          ))}
        </nav>
      </div>
      <ErrorNote error={p.status.error} />
      {p.loading ? <Loading label="Checking your setup" /> : (
        <div className="max-w-4xl space-y-6">
          <Basics status={p.status.data} done={p.steps[0].done} />
          <TelegramStep status={p.status.data} done={p.steps[1].done} />
          <AiStep done={p.steps[2].done} />
          <PlatformStep platform="youtube" status={p.status.data} done={p.steps[3].done} />
          <PlatformStep platform="facebook" status={p.status.data} done={p.steps[4].done} />
          <PlatformStep platform="tiktok" status={p.status.data} done={p.steps[5].done} />
          <PlatformStep platform="x" status={p.status.data} done={p.steps[6].done} />
          <ResearchStep status={p.status.data} done={p.steps[7].done} />
          <ScheduleStep done={p.steps[8].done} />
          <FirstVideoStep done={p.steps[9].done} />
        </div>
      )}
    </>
  );
}

function Step({ id, n, title, done, optional, intro, children }: { id: string; n: number; title: string; done: boolean; optional?: boolean; intro: ReactNode; children?: ReactNode }) {
  return (
    <section id={id} aria-labelledby={`${id}-title`} className={`scroll-mt-6 rounded-xl border bg-surface p-5 ${done ? "border-penny/40" : "border-line"}`}>
      <h2 id={`${id}-title`} className="flex items-center gap-2 font-display text-lg font-semibold">
        {done ? <CircleCheck size={20} className="text-penny" aria-hidden /> : <CircleDashed size={20} className="text-muted" aria-hidden />}
        {n}. {title}{optional && <span className="text-sm font-normal text-muted">(optional)</span>}
        <span className="sr-only">{done ? "(done)" : "(not done yet)"}</span>
      </h2>
      <div className="mt-2 text-sm text-muted">{intro}</div>
      {children && <div className="mt-4 space-y-4">{children}</div>}
    </section>
  );
}

function CopyValue({ label, value }: { label: string; value: string }) {
  const toast = useToast();
  return (
    <div className="text-sm">
      <p className="text-muted">{label}</p>
      <div className="mt-1 flex items-center gap-2">
        <code className="min-w-0 flex-1 truncate rounded-lg bg-sunken px-3 py-2 text-xs">{value}</code>
        <button type="button" className="btn-quiet" onClick={() => navigator.clipboard.writeText(value).then(() => toast("Copied"), () => toast("Couldn't copy: select it and copy by hand", "bad"))}>
          <Copy size={14} aria-hidden />Copy
        </button>
      </div>
    </div>
  );
}

function Where({ state }: { state?: ValueState }) {
  if (!state) return null;
  if (state.dashboard && !state.readable) return <span className="rounded-md bg-alert-soft px-2 py-0.5 text-xs text-alert">Saved but unreadable: save it again</span>;
  if (state.dashboard) return (
    <span className="flex flex-wrap gap-1.5">
      <span className="rounded-md bg-penny-soft px-2 py-0.5 text-xs text-penny">Saved in dashboard {state.hint}</span>
      {state.github && <span className="rounded-md bg-sunken px-2 py-0.5 text-xs text-muted">Also in GitHub: safe to remove there</span>}
    </span>
  );
  if (state.github) return <span className="rounded-md bg-sunken px-2 py-0.5 text-xs text-muted">Using the GitHub secret</span>;
  return <span className="rounded-md bg-sunken px-2 py-0.5 text-xs text-muted">Not set</span>;
}

function TestLine({ test }: { test: Test | null }) {
  if (!test) return null;
  const Icon = test.ok === true ? CircleCheck : test.ok === false ? CircleAlert : Info;
  return (
    <p role="status" className={`flex items-start gap-2 rounded-lg px-3 py-2 text-sm ${test.ok === true ? "bg-penny-soft text-penny" : test.ok === false ? "bg-alert-soft text-alert" : "bg-sunken text-ink"}`}>
      <Icon size={16} className="mt-0.5 shrink-0" aria-hidden />{test.detail}
    </p>
  );
}

function SecretField({ name, label, help, state, secret = true, placeholder }: { name: string; label: string; help?: ReactNode; state?: ValueState; secret?: boolean; placeholder?: string }) {
  const qc = useQueryClient();
  const toast = useToast();
  const [value, setValue] = useState("");
  const [show, setShow] = useState(false);
  const [test, setTest] = useState<Test | null>(null);
  const save = useMutation({
    mutationFn: () => callWorker<{ hint: string; test: Test; telegram?: { ok: boolean; problem?: string } }>("/api/setup/save", { name, value }),
    onSuccess: (r) => {
      setValue("");
      setTest(r.telegram && !r.telegram.ok ? { ok: false, detail: r.telegram.problem ?? "Telegram couldn't be linked." } : r.test);
      toast(`${label} saved`);
      qc.invalidateQueries({ queryKey: ["setup-status"] });
    },
    onError: (e) => setTest({ ok: false, detail: (e as Error).message }),
  });
  const check = useMutation({
    mutationFn: () => callWorker<{ test: Test }>("/api/setup/test", { name }),
    onSuccess: (r) => setTest(r.test),
    onError: (e) => setTest({ ok: false, detail: (e as Error).message }),
  });
  const remove = useMutation({
    mutationFn: () => callWorker("/api/setup/remove", { name }),
    onSuccess: () => { toast(`${label} removed from the dashboard${state?.github ? "; the GitHub secret is used again" : ""}`); setTest(null); qc.invalidateQueries({ queryKey: ["setup-status"] }); },
    onError: (e) => toast((e as Error).message, "bad"),
  });
  const id = `f-${name}`;
  return (
    <div className="rounded-lg border border-line p-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <label htmlFor={id} className="text-sm font-medium text-ink">{label}</label>
        <Where state={state} />
      </div>
      {help && <p className="mt-1 text-xs text-muted">{help}</p>}
      <form className="mt-2 flex flex-wrap gap-2" onSubmit={(e) => { e.preventDefault(); if (value.trim()) save.mutate(); }}>
        <div className="relative min-w-[14rem] flex-1">
          <input id={id} className="field pr-10" type={secret && !show ? "password" : "text"} autoComplete="off" spellCheck={false}
            value={value} onChange={(e) => setValue(e.target.value)} placeholder={placeholder ?? (state?.dashboard || state?.github ? "Paste a new value to replace it" : "Paste it here")} />
          {secret && <button type="button" className="absolute right-2 top-1/2 -translate-y-1/2 p-1 text-muted" aria-label={show ? "Hide" : "Show"} onClick={() => setShow((s) => !s)}>
            {show ? <EyeOff size={15} /> : <Eye size={15} />}</button>}
        </div>
        <button className="btn-primary" disabled={!value.trim() || save.isPending}>{save.isPending ? "Saving…" : "Save & test"}</button>
        {(state?.dashboard || state?.github) && <button type="button" className="btn-quiet" onClick={() => check.mutate()} disabled={check.isPending}>{check.isPending ? "Testing…" : "Test"}</button>}
        {state?.dashboard && <button type="button" className="btn-quiet" onClick={() => remove.mutate()} disabled={remove.isPending}>Remove</button>}
      </form>
      <div className="mt-2"><TestLine test={test} /></div>
    </div>
  );
}

function Basics({ status, done }: { status?: Status; done: boolean }) {
  const label: Record<string, string> = { database: "Database", encryption: "Encryption key", github: "GitHub (starts the engine)", dashboard: "Dashboard address" };
  return (
    <Step id="basics" n={1} title="The basics" done={done} intro={<>These must stay as GitHub secrets, because the studio needs them before it can reach its own database. If you followed the guide, they're already there.</>}>
      <ul className="space-y-1.5 text-sm">
        {Object.entries(status?.core ?? {}).map(([k, c]) => (
          <li key={k} className="flex items-start gap-2">
            {c.ok ? <CircleCheck size={16} className="mt-0.5 text-penny" aria-hidden /> : <CircleAlert size={16} className="mt-0.5 text-alert" aria-hidden />}
            <span><span className="font-medium">{label[k] ?? k}:</span> <span className="text-muted">{c.detail}</span></span>
          </li>
        ))}
      </ul>
      <details className="text-sm">
        <summary className="cursor-pointer text-muted">Must stay in GitHub ({status?.core_names.length ?? 0})</summary>
        <p className="mt-2 text-xs text-muted">Never delete these: {status?.core_names.join(", ")}.</p>
      </details>
    </Step>
  );
}

function TelegramStep({ status, done }: { status?: Status; done: boolean }) {
  const chat = useSetting<string | null>("telegram_chat_id", null).data;
  const toast = useToast();
  const [code, setCode] = useState<string | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const get = useMutation({
    mutationFn: () => callWorker<{ code: string; telegram?: { ok: boolean; problem?: string } }>("/api/telegram/link-code", {}),
    onSuccess: (d) => { setCode(d.code); setProblem(d.telegram && !d.telegram.ok ? d.telegram.problem ?? "The bot isn't connected." : null); },
    onError: (e) => toast((e as Error).message, "bad"),
  });
  const hasToken = Boolean(status?.values.TELEGRAM_BOT_TOKEN?.dashboard || status?.values.TELEGRAM_BOT_TOKEN?.github);
  return (
    <Step id="telegram" n={2} title="Telegram" done={done} intro={<>Alerts on your phone, and approve, pause or switch Auto Review &amp; Post from anywhere.
      In Telegram, open <b>@BotFather</b>, send <code>/newbot</code>, choose a name and a username ending in <code>bot</code>, then copy the token it sends you.</>}>
      <SecretField name="TELEGRAM_BOT_TOKEN" label="Bot token" state={status?.values.TELEGRAM_BOT_TOKEN} placeholder="123456789:AA…"
        help="The private link between the bot and the studio is made for you when you save." />
      <div className="rounded-lg border border-line p-3 text-sm">
        <p className="font-medium text-ink">Link your chat {chat && <span className="ml-1 text-penny">✅ linked</span>}</p>
        <p className="mt-1 text-xs text-muted">Press the button, then send the line it shows to your bot in Telegram.</p>
        <button className="btn-quiet mt-2" onClick={() => get.mutate()} disabled={get.isPending || !hasToken}>{chat ? "Link a different chat" : "Get a link code"}</button>
        {code && <p className="mt-2 rounded-lg bg-sunken px-3 py-2">Send to your bot: <code className="font-semibold">/link {code}</code></p>}
        {problem && <p role="alert" className="mt-2 rounded-lg bg-alert-soft px-3 py-2 text-alert">{problem}</p>}
      </div>
    </Step>
  );
}

function AiStep({ done }: { done: boolean }) {
  const check = useSetting<{ results?: { provider: string; status: string }[]; checked_at?: string } | null>("provider_check", null).data;
  const ok = (check?.results ?? []).filter((r) => r.status === "ok").map((r) => r.provider);
  return (
    <Step id="ai" n={3} title="AI keys" done={done} intro={<>The writers and reviewers. Free keys are enough. For the fewest delays, add several keys to
      <b> Gemini</b> (best writer), <b>Cloudflare</b> (always available), <b>Z.ai</b>, <b>Cerebras</b> and <b>SambaNova</b>. Add each key in AI APIs and press Test.</>}>
      <p className="text-sm">{ok.length ? <>Working now: {ok.join(", ")}.</> : "No AI service has passed a check yet."}
        {check?.checked_at && <span className="text-muted"> Last checked {new Date(check.checked_at).toLocaleString()}.</span>}</p>
      <Link to="/api" className="btn-primary">Open AI APIs</Link>
    </Step>
  );
}

const PLATFORM_STEPS: Record<Platform, { n: number; names: [string, string]; labels: [string, string]; where: ReactNode }> = {
  youtube: { n: 4, names: ["GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET"], labels: ["Client ID", "Client secret"], where: <>
    Go to <b>console.cloud.google.com</b> → create a project → <b>APIs &amp; Services → Library</b> → enable <b>YouTube Data API v3</b>.
    Then <b>OAuth consent screen</b> (External, add yourself as a test user) → <b>Credentials → Create credentials → OAuth client ID → Web application</b>.
    Under <b>Authorised redirect URIs</b> paste the address below, create it, and copy the Client ID and Client secret here.</> },
  facebook: { n: 5, names: ["FACEBOOK_APP_ID", "FACEBOOK_APP_SECRET"], labels: ["App ID", "App secret"], where: <>
    Go to <b>developers.facebook.com → My Apps → Create app</b> (type Business). Add <b>Facebook Login for Business</b>; in its settings paste the address below under
    <b> Valid OAuth Redirect URIs</b>. Then <b>App settings → Basic</b>: copy the App ID and App secret here.</> },
  tiktok: { n: 6, names: ["TIKTOK_CLIENT_KEY", "TIKTOK_CLIENT_SECRET"], labels: ["Client key", "Client secret"], where: <>
    Go to <b>developers.tiktok.com → Manage apps → Connect an app</b>. Add <b>Login Kit</b> and <b>Content Posting API</b>, paste the address below as the
    <b> Redirect URI</b>, then copy the Client key and Client secret here. Until TikTok approves the app, posts are saved as drafts or come to you as quick jobs.</> },
  x: { n: 7, names: ["X_CLIENT_ID", "X_CLIENT_SECRET"], labels: ["OAuth 2.0 Client ID", "OAuth 2.0 Client secret"], where: <>
    Go to <b>developer.x.com → Projects &amp; Apps</b> → your app → <b>User authentication settings → Set up</b>: OAuth 2.0, type <b>Web App</b>, Read and write,
    and paste the address below as the <b>Callback URI</b>. Then <b>Keys and tokens</b>: copy the OAuth 2.0 Client ID and Client secret here. X is the only paid service (capped at $1 a month).</> },
};

function PlatformStep({ platform, status, done }: { platform: Platform; status?: Status; done: boolean }) {
  const cfg = PLATFORM_STEPS[platform];
  const accounts = useAccounts();
  const toast = useToast();
  const connect = useMutation({
    mutationFn: async (id: string) => (await callWorker<{ url: string }>("/api/oauth/start", { account_id: id })).url,
    onSuccess: (url) => { window.location.href = url; },
    onError: (e) => toast((e as Error).message, "bad"),
  });
  const mine = (accounts.data ?? []).filter((a) => a.platform === platform);
  const ready = cfg.names.every((n) => status?.values[n]?.dashboard || status?.values[n]?.github);
  return (
    <Step id={platform} n={cfg.n} title={PLATFORM_NAME[platform]} done={done} intro={cfg.where}>
      <CopyValue label="Redirect address to paste on the platform" value={`${workerUrl}/oauth/${platform}/callback`} />
      <div className="grid gap-3 sm:grid-cols-2">
        <SecretField name={cfg.names[0]} label={cfg.labels[0]} state={status?.values[cfg.names[0]]} secret={false} />
        <SecretField name={cfg.names[1]} label={cfg.labels[1]} state={status?.values[cfg.names[1]]} />
      </div>
      <ul className="divide-y divide-line rounded-lg border border-line">
        {mine.map((a) => {
          const st = a.oauth_connections?.status ?? "disconnected";
          return (
            <li key={a.id} className="flex flex-wrap items-center gap-3 px-3 py-2 text-sm">
              <span className="min-w-0 flex-1 font-medium">{a.label}</span>
              <span className={`text-xs ${st === "connected" ? "text-penny" : st === "disconnected" ? "text-muted" : "text-alert"}`}>
                {st === "connected" ? "✅ Connected" : st === "disconnected" ? "Not connected" : "Reconnect needed"}</span>
              <button className={st === "connected" ? "btn-quiet" : "btn-primary"} disabled={!ready || connect.isPending} onClick={() => connect.mutate(a.id)}>
                {st === "connected" ? "Reconnect" : "Connect"}</button>
            </li>
          );
        })}
      </ul>
      {!ready && <p className="text-xs text-muted">Save both values above, then press Connect and sign in with the account you post from.</p>}
    </Step>
  );
}

function ResearchStep({ status, done }: { status?: Status; done: boolean }) {
  return (
    <Step id="research" n={8} title="Research and stock photo keys" optional done={done} intro="More sources for ideas and better pictures. All free. Skip any you don't want.">
      <SecretField name="YOUTUBE_API_KEY" label="YouTube Data API key" state={status?.values.YOUTUBE_API_KEY}
        help="Google Cloud → APIs & Services → Credentials → Create credentials → API key (same project, with YouTube Data API v3 enabled)." />
      <SecretField name="PEXELS_API_KEY" label="Pexels API key" state={status?.values.PEXELS_API_KEY} help="pexels.com/api → Your API key." />
      <SecretField name="PIXABAY_API_KEY" label="Pixabay API key" state={status?.values.PIXABAY_API_KEY} help="pixabay.com/api/docs → your key is shown when signed in." />
      <SecretField name="FRED_API_KEY" label="FRED API key (economic data for Penny)" state={status?.values.FRED_API_KEY} help="fredaccount.stlouisfed.org → API Keys → Request API key." />
      <SecretField name="SEC_USER_AGENT" label="SEC contact (name and email)" secret={false} state={status?.values.SEC_USER_AGENT}
        placeholder="Your Name you@example.com" help="SEC asks every app to say who it is. Not a password." />
      {status?.engine_checked_at && <p className="text-xs text-muted">GitHub secrets last checked by the engine {new Date(status.engine_checked_at).toLocaleString()}.</p>}
    </Step>
  );
}

function ScheduleStep({ done }: { done: boolean }) {
  const progress = useSetting<Record<string, unknown>>("setup_progress", {}).data ?? {};
  const save = useSaveSetting();
  return (
    <Step id="schedule" n={9} title="Posting schedule" done={done} intro="Which days and times each account posts, and how many posts a week. The default works well; change it any time.">
      <div className="flex flex-wrap gap-2">
        <Link to="/settings#posting-schedule" className="btn-quiet">Open the posting schedule</Link>
        {!done && <button className="btn-primary" onClick={() => save.mutate({ key: "setup_progress", value: { ...progress, schedule_reviewed: true } })}>The schedule looks right</button>}
      </div>
    </Step>
  );
}

function FirstVideoStep({ done }: { done: boolean }) {
  return (
    <Step id="first" n={10} title="Your first video" done={done} intro={<>Generate ideas, send one to the Studio, and review the package when it arrives (usually within an hour).
      After a week or two of reviewing, you can switch on <b>Auto Review &amp; Post</b> in Settings → Automation.</>}>
      <div className="flex flex-wrap gap-2">
        <Link to="/ideas" className="btn-primary">Generate ideas</Link>
        <Link to="/activity" className="btn-quiet">Watch the Activity page</Link>
      </div>
    </Step>
  );
}

