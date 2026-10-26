import JobActions from "../components/JobActions";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronLeft, ChevronRight, Pause, Play, PlusCircle } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";
import ClearButton from "../components/ClearButton";
import DraftList from "../components/Drafts";
import { AutoPostBadge } from "../components/AutoPostToggle";
import Rundown from "../components/Rundown";
import { Confirm, ErrorNote, HostTag, Loading, NotConfirmed, PageHeader, StatusBadge, useToast } from "../components/ui";
import { must, useAccounts, useSaveSetting, useSetting, useTimezone } from "../lib/api";
import { useCleared, visibleAfterClear } from "../lib/clear";
import { fixFor } from "../lib/labels";
import { jobTitle, stillFailing, useRunningJobs } from "../lib/activity";
import { fmtDateTime, localDay, statusText, weekDays } from "../lib/format";
import { useKeyCheck, useReadiness } from "../lib/readiness";
import { projectPath } from "../lib/routes";
import { signedUrl, supabase } from "../lib/supabase";
import type { Post, Project } from "../lib/types";

export const POST_SELECT =
  "id, scheduled_at, status, last_error, social_account_id, variant_id, content_variants(title, kind, body, project_id, content_projects(channel_slug, title)), social_accounts(label, platform), published_posts(url, method)";

export default function Home() {
  const tz = useTimezone();
  const [offset, setOffset] = useState(0);
  const base = new Date(Date.now() + offset * 7 * 86_400_000);
  const days = weekDays(base, tz);
  const accounts = useAccounts();
  const ready = useReadiness();
  const posts = useQuery({
    queryKey: ["posts", days[0]],
    queryFn: async () => {
      const from = new Date(Date.parse(`${days[0]}T00:00:00Z`) - 86_400_000).toISOString();
      const to = new Date(Date.parse(`${days[6]}T23:59:59Z`) + 86_400_000).toISOString();
      return (await must(supabase.from("scheduled_posts").select(POST_SELECT).gte("scheduled_at", from).lte("scheduled_at", to).neq("status", "cancelled"))) as unknown as Post[];
    },
  });
  const week = posts.data ?? [];
  const counts = {
    total: week.length,
    waiting: week.filter((p) => p.status === "pending_approval").length,
    done: week.filter((p) => p.status === "published").length,
    problems: week.filter((p) => ["failed", "blocked", "needs_review", "needs_manual"].includes(p.status)).length,
  };
  return (
    <>
      <PageHeader title="Home" intro={posts.isSuccess ? summaryLine(counts) : posts.isError ? "Couldn't load this week's posts." : "Loading this week…"}
        actions={<CreateButton canCreate={ready.canCreate} reason={ready.blockers[0]?.text} />} />
      <div className="-mt-3 mb-6 max-w-md"><AutoPostBadge /></div>
      <NeedsYou readiness={ready} />
      <div className="mt-8"><DraftList title="Unfinished" compact /></div>
      <div className="mt-8 grid grid-cols-1 gap-8 lg:grid-cols-2">
        <BeingMade />
        <NextPosts tz={tz} />
      </div>
      <section aria-labelledby="rundown-title" className="mt-10">
        <div className="mb-3 flex items-center justify-between gap-3">
          <h2 id="rundown-title" className="section-title">This week</h2>
          <WeekPicker offset={offset} setOffset={setOffset} />
        </div>
        {accounts.isLoading || posts.isLoading ? <Loading /> : accounts.isError || posts.isError ? <NotConfirmed q={accounts.isError ? accounts : posts} what="this week's plan" /> : (
          <Rundown accounts={accounts.data ?? []} posts={week} days={days} tz={tz} today={localDay(new Date(), tz)} />
        )}
        <p className="mt-2 flex flex-wrap gap-x-5 gap-y-1 text-xs text-muted">
          <span className="inline-flex items-center gap-1.5"><HostTag channel="ai" /> AI topics</span>
          <span className="inline-flex items-center gap-1.5"><HostTag channel="money" /> Money topics</span>
          <span>Dashed outline: waiting for approval</span>
          <span>Red outline: needs attention</span>
        </p>
      </section>
      <div className="mt-10 grid grid-cols-1 gap-8 lg:grid-cols-[1.3fr_1fr]">
        <details className="rounded-xl border border-line bg-surface">
          <summary className="cursor-pointer px-4 py-3 text-sm font-semibold">Studio health <span className="font-normal text-muted">· AI services, X spending, problems this week</span></summary>
          <div className="border-t border-line p-3"><Health /></div>
        </details>
        <div className="flex flex-col items-start gap-3">
          <TelegramHint />
          <PauseButton />
        </div>
      </div>
    </>
  );
}

function CreateButton({ canCreate, reason }: { canCreate: boolean; reason?: string }) {
  if (canCreate) return <Link to="/create" className="btn-primary"><PlusCircle size={16} aria-hidden />Create content</Link>;
  return (
    <span className="flex flex-col items-end gap-1">
      <button className="btn-primary" disabled aria-describedby="create-blocked"><PlusCircle size={16} aria-hidden />Create content</button>
      <span id="create-blocked" className="text-xs text-alert">{reason ?? "The studio can't create right now."}</span>
    </span>
  );
}

function TelegramHint() {
  const linked = useSetting<string | null>("telegram_chat_id", null);
  const [hidden, setHidden] = useState(() => { try { return localStorage.getItem("studio-hide-telegram-hint") === "1"; } catch { return false; } });
  if (!linked.isSuccess || linked.data || hidden) return null;  // only when the database confirms it isn't linked
  return (
    <p className="flex items-start gap-2 rounded-lg bg-sunken px-3 py-2 text-sm">
      <span>Recommended: get alerts on your phone. <Link to="/settings/notifications" className="text-pixel underline">Link Telegram</Link> (optional).</span>
      <button className="text-xs text-muted hover:text-ink" aria-label="Hide this tip" onClick={() => { setHidden(true); try { localStorage.setItem("studio-hide-telegram-hint", "1"); } catch { /* private mode */ } }}>Hide</button>
    </p>
  );
}

type Need = { key: string; tone: "bad" | "info" | "warn"; text: string; action: React.ReactNode };

function NeedsYou({ readiness }: { readiness: ReturnType<typeof useReadiness> }) {
  const keyCheck = useKeyCheck();
  const toast = useToast();
  const data = useQuery({
    queryKey: ["home-needs-you"],
    refetchInterval: 30_000,
    queryFn: async () => {
      const since = new Date(Date.now() - 3 * 86_400_000).toISOString();
      const types = ["produce_idea", "run_mission", "run_production", "run_research", "generate_ideas", "regenerate_script", "rerender_preview", "weekly_production", "weekly_research"];
      const [failed, done, posts, review, accounts] = await Promise.all([
        must(supabase.from("generation_jobs").select("id, job_type, error_message, input, project_id, updated_at, content_projects(title)").eq("status", "failed")
          .in("job_type", types).gte("updated_at", since).order("updated_at", { ascending: false }).limit(20)),
        must(supabase.from("generation_jobs").select("job_type, input, project_id, updated_at").eq("status", "completed")
          .in("job_type", types).gte("updated_at", since).limit(200)),
        must(supabase.from("scheduled_posts").select("id, status, last_error, scheduled_at, social_accounts(label)").in("status", ["failed", "blocked", "needs_review"]).gte("updated_at", since).limit(5)),
        must(supabase.from("content_projects").select("id, title, status, channel_slug").in("status", ["ready_for_review", "needs_attention"]).is("parent_project_id", null).order("created_at", { ascending: false }).limit(6)),
        must(supabase.from("social_accounts").select("id, label, enabled, oauth_connections(status)")),
      ]);
      const jobs = stillFailing(failed as any[], done as any[]).slice(0, 4);  // a retry that worked clears its failure
      return { jobs, posts: posts as any[], review: review as any[], accounts: accounts as any[] };
    },
  });
  const cleared = useCleared();
  const needs: Need[] = [];
  for (const b of readiness.blockers) needs.push({ key: b.text, tone: "bad", text: b.text, action: <Link className="btn-quiet" to={b.to}>Fix it</Link> });
  if (readiness.checkError || readiness.aiError) {
    needs.push({ key: "ai-unknown", tone: "warn", text: readiness.checkError ? "Couldn't load the last AI key check, so it isn't known whether the AI services work." : "Couldn't load the AI services and models.",
      action: <Link className="btn-quiet" to="/settings/ai">Open AI services</Link> });
  } else if (readiness.checkedAt && readiness.stale || !readiness.checkedAt) {
    needs.push({ key: "stale", tone: "warn", text: readiness.checkedAt ? `The AI key check is ${hoursAgo(readiness.checkedAt)} old; results may have changed.` : "The AI keys haven't been checked yet.",
      action: <button className="btn-quiet" disabled={keyCheck.running || keyCheck.run.isPending} onClick={() => keyCheck.run.mutate(undefined, { onSuccess: () => toast("Testing the AI keys. Results appear in a few minutes."), onError: (e) => toast((e as Error).message, "bad") })}>{keyCheck.running ? "Testing…" : "Test again"}</button> });
  }
  if (!readiness.checkError && readiness.uncoveredRoles.length && readiness.checkedAt) {
    needs.push({ key: "roles", tone: "warn", text: `No AI service that passed the last check does: ${readiness.uncoveredRoles.join(", ")}. Packages may stop at that step.`, action: <Link className="btn-quiet" to="/settings/ai">Check AI services</Link> });
  }
  for (const j of data.data?.jobs ?? []) {
    const fix = fixFor(j.error_message);
    needs.push({ key: j.id, tone: "bad", text: `${jobTitle(j)} didn't work: ${String(j.error_message ?? "").slice(0, 140)}`,
      action: j.project_id ? <Link className="btn-quiet" to={projectPath(j.project_id)}>Open</Link>
        : j.job_type === "produce_idea" && (j.input?.generated_idea_id || j.input?.content_idea_id)
          ? <Link className="btn-quiet" to={`/create?${new URLSearchParams({ step: "progress", kind: j.input.generated_idea_id ? "generated" : "research", id: j.input.generated_idea_id ?? j.input.content_idea_id, ...(j.input.channel ? { channel: j.input.channel } : {}) })}`}>Fix problem</Link>
        : fix ? <Link className="btn-quiet" to={fix.to}>{fix.label}</Link> : null });
  }
  for (const p of data.data?.posts ?? []) {
    needs.push({ key: p.id, tone: "bad", text: `${p.social_accounts?.label ?? "A post"}: ${statusText(p.status)}${p.last_error ? `: ${String(p.last_error).slice(0, 100)}` : ""}`, action: <Link className="btn-quiet" to={`/calendar?post=${p.id}`}>Open in Calendar</Link> });
  }
  for (const a of data.data?.accounts ?? []) {
    const st = (Array.isArray(a.oauth_connections) ? a.oauth_connections[0] : a.oauth_connections)?.status;
    if (a.enabled && ["expired", "needs_reauth", "error"].includes(st)) needs.push({ key: a.id, tone: "bad", text: `${a.label} needs reconnecting before it can post.`, action: <Link className="btn-quiet" to="/settings/accounts">Reconnect</Link> });
  }
  for (const r of data.data?.review ?? []) {
    needs.push({ key: r.id, tone: "info", text: `"${r.title}" ${r.status === "needs_attention" ? "needs a look" : "is ready for review"}`, action: <Link className="btn-primary" to={projectPath(r.id)}>Review</Link> });
  }
  return (
    <section aria-labelledby="needs-title">
      <h2 id="needs-title" className="section-title mb-3">Needs you</h2>
      {data.isLoading || readiness.loading ? <Loading /> : (
        <>
          <NotConfirmed q={data} what="what needs you" />
          {needs.length === 0 ? (data.isError ? null : <p className="rounded-xl border border-dashed border-line px-4 py-3 text-sm text-muted">Nothing needs you right now.</p>) : (
            <ul className="divide-y divide-line rounded-xl border border-line bg-surface">
              {needs.map((n) => (
                <li key={n.key} className="grid grid-cols-[auto_minmax(0,1fr)] items-start gap-3 px-4 py-3 sm:flex sm:items-center">
                  <span className={`h-2 w-2 shrink-0 rounded-full ${n.tone === "bad" ? "bg-alert" : n.tone === "warn" ? "bg-gold" : "bg-pixel"}`} aria-hidden />
                  <span className="min-w-0 flex-1 text-sm">{n.text}</span>
                  <div className="col-start-2 sm:ml-auto">{n.action}</div>
                </li>
              ))}
            </ul>
          )}
          <div className="mt-4"><ManualTasks /></div>
        </>
      )}
    </section>
  );
}

function hoursAgo(iso: string): string {
  const h = Math.round((Date.now() - Date.parse(iso)) / 3_600_000);
  return h < 48 ? `${h} hours` : `${Math.round(h / 24)} days`;
}

function BeingMade() {
  const running = useRunningJobs();
  const jobs = running.data ?? [];
  return (
    <section aria-labelledby="making-title">
      <h2 id="making-title" className="section-title mb-3">Being made now</h2>
      {running.isLoading ? <Loading /> : running.isError ? <NotConfirmed q={running} what="what's being made" /> : jobs.length === 0 ? <p className="text-sm text-muted">Nothing is being made right now.</p> : (
        <ul className="space-y-2">
          {jobs.slice(0, 4).map((j) => (
            <li key={j.id} className="rounded-xl border border-line bg-surface px-4 py-3 text-sm">
              <p className="font-medium">{jobTitle(j)}</p><JobActions job={j} />
              <p className="text-muted">{j.status === "queued" ? "Waiting to start (within 15 minutes)" : j.progress?.label ?? "Working…"}</p>
            </li>
          ))}
        </ul>
      )}
      <Link to="/activity" className="mt-2 inline-block text-sm text-pixel hover:underline">See Activity</Link>
    </section>
  );
}

function NextPosts({ tz }: { tz: string }) {
  const next = useQuery({
    queryKey: ["next-posts"],
    queryFn: async () => (await must(supabase.from("scheduled_posts").select("id, scheduled_at, status, social_accounts(label), content_variants(title, kind, content_projects(title))")
      .in("status", ["scheduled", "pending_approval"]).gte("scheduled_at", new Date().toISOString()).order("scheduled_at").limit(5))) as any[],
  });
  return (
    <section aria-labelledby="next-title">
      <h2 id="next-title" className="section-title mb-3">Next posts</h2>
      {next.isLoading ? <Loading /> : next.isError ? <NotConfirmed q={next} what="the next posts" /> : (next.data ?? []).length === 0 ? <p className="text-sm text-muted">Nothing planned yet. <Link to="/create" className="text-pixel underline">Create content</Link> to fill your week.</p> : (
        <ul className="divide-y divide-line rounded-xl border border-line bg-surface text-sm">
          {(next.data ?? []).map((p) => (
            <li key={p.id}>
              <Link to={`/calendar?post=${p.id}`} className="flex flex-wrap items-center gap-3 px-4 py-2.5 hover:bg-sunken">
                <span className="w-28 tabular text-muted">{fmtDateTime(p.scheduled_at, tz)}</span>
                <span className="min-w-0 flex-1 truncate">{p.social_accounts?.label} · {p.content_variants?.title || p.content_variants?.content_projects?.title}</span>
                <StatusBadge status={p.status} />
              </Link>
            </li>
          ))}
        </ul>
      )}
      <Link to="/calendar" className="mt-2 inline-block text-sm text-pixel hover:underline">Open calendar</Link>
    </section>
  );
}

export function WeekPicker({ offset, setOffset }: { offset: number; setOffset: (n: number) => void }) {
  return (
    <div className="flex items-center gap-1" role="group" aria-label="Choose week">
      <button className="btn-quiet px-2.5 py-1" onClick={() => setOffset(offset - 1)} aria-label="Previous week"><ChevronLeft size={16} aria-hidden /></button>
      <button className="btn-quiet px-2.5 py-1" onClick={() => setOffset(0)} disabled={offset === 0}>This week</button>
      <button className="btn-quiet px-2.5 py-1" onClick={() => setOffset(offset + 1)} aria-label="Next week"><ChevronRight size={16} aria-hidden /></button>
    </div>
  );
}

function summaryLine(c: { total: number; waiting: number; done: number; problems: number }): string {
  if (!c.total) return "No posts planned this week yet. Saturday's research and Sunday's production will fill it.";
  const parts = [`${c.total} posts planned`, `${c.done} published`];
  if (c.waiting) parts.push(`${c.waiting} waiting for approval`);
  if (c.problems) parts.push(`${c.problems} need attention`);
  return parts.join(", ") + ".";
}

export function PauseButton() {
  const q = useSetting<boolean>("paused", false);
  const paused = q.data === true;
  const save = useSaveSetting();
  const toast = useToast();
  const [ask, setAsk] = useState(false);
  if (!q.isSuccess) return <NotConfirmed q={q} what="whether publishing is paused" compact />;  // never offer the wrong action
  return (
    <>
      <button className={paused ? "btn-primary" : "btn-danger"} onClick={() => setAsk(true)} disabled={save.isPending}>
        {paused ? <Play size={16} aria-hidden /> : <Pause size={16} aria-hidden />}
        {paused ? "Resume publishing" : "Pause publishing"}
      </button>
      <Confirm
        open={ask}
        title={paused ? "Resume publishing?" : "Pause all publishing?"}
        body={paused ? "Approved posts will go out at their scheduled times again." : "Nothing will be posted on any account until you resume. Production keeps running."}
        confirmLabel={paused ? "Resume publishing" : "Pause publishing"}
        danger={!paused}
        onCancel={() => setAsk(false)}
        onConfirm={() => {
          setAsk(false);
          save.mutate({ key: "paused", value: !paused }, {
            onSuccess: () => toast(paused ? "Publishing resumed" : "Publishing paused"),
            onError: (e) => toast(`${paused ? "Publishing is still paused" : "Publishing was not paused"}: ${(e as Error).message}`, "bad"),
          });
        }}
      />
    </>
  );
}

function ManualTasks() {
  const qc = useQueryClient();
  const toast = useToast();
  const tasks = useQuery({
    queryKey: ["manual_tasks"],
    queryFn: async () => (await must(supabase.from("manual_tasks").select("*").eq("status", "open").order("created_at", { ascending: false }).limit(10))) as any[],
  });
  const done = useMutation({
    mutationFn: async (id: string) => must(supabase.rpc("complete_manual_task", { p_task_id: id, p_url: null })),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["manual_tasks"] }); qc.invalidateQueries({ queryKey: ["posts"] }); toast("Marked as done"); },
    onError: (e) => toast((e as Error).message, "bad"),
  });
  if (!tasks.data?.length) return null;
  return (
    <section aria-labelledby="tasks-title">
      <h2 id="tasks-title" className="section-title mb-3">Your quick jobs</h2>
      <ul className="space-y-3">
        {tasks.data.map((t) => (
          <li key={t.id} className="rounded-xl border border-gold/60 bg-surface p-4">
            <p className="text-sm font-medium">{t.title}</p>
            <p className="mt-1 text-sm text-muted">{t.instructions}</p>
            <div className="mt-3 flex gap-2">
              {t.asset_key && <DownloadButton storageKey={t.asset_key} />}
              {t.deep_link && <a className="btn-quiet" href={t.deep_link} target="_blank" rel="noreferrer">Open</a>}
              <button className="btn-primary" onClick={() => done.mutate(t.id)} disabled={done.isPending}>Done</button>
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}

function DownloadButton({ storageKey }: { storageKey: string }) {
  const toast = useToast();
  return (
    <button className="btn-quiet" onClick={async () => {
      try {
        const url = await signedUrl(storageKey, 600);
        if (url) window.location.href = url; else toast("That file has expired. Ask for a new render from Review Studio.", "bad");
      } catch (e) {
        toast(`Couldn't get the download link: ${(e as Error).message}`, "bad");
      }
    }}>Download video</button>
  );
}

function Health() {
  const health = useQuery({
    queryKey: ["health"],
    queryFn: async () => {
      const since = new Date(Date.now() - 7 * 86_400_000).toISOString();
      const [failedRaw, done, providers, budget, reservations] = await Promise.all([
        must(supabase.from("generation_jobs").select("id, job_type, error_message, status, input, project_id, updated_at").in("status", ["failed", "blocked"]).gte("created_at", since).order("updated_at", { ascending: false }).limit(40)),
        must(supabase.from("generation_jobs").select("job_type, input, project_id, updated_at").eq("status", "completed").gte("created_at", since).limit(500)),
        must(supabase.from("ai_providers").select("name, enabled, last_error, last_success_at, circuit_open_until")),
        must(supabase.from("budgets").select("monthly_cap_usd").eq("service", "x_api")),
        must(supabase.from("budget_reservations").select("amount_usd, status").eq("service", "x_api").eq("month", new Date().toISOString().slice(0, 7) + "-01")),
      ]);
      const failed = stillFailing(failedRaw as any[], done as any[]).slice(0, 20);
      return { failed, providers: providers as any[], cap: Number((budget as any[])[0]?.monthly_cap_usd ?? 1), spent: (reservations as any[]).filter((r) => r.status === "committed").reduce((a, r) => a + Number(r.amount_usd), 0) };
    },
  });
  const cleared = useCleared();
  if (health.isLoading) return <Loading />;
  const d = health.data;
  if (!d) return <ErrorNote error={health.error} onRetry={() => health.refetch()} retrying={health.isFetching} />;
  const problems = visibleAfterClear(d.failed, cleared.map, "rundown_problems", (f) => f.updated_at).slice(0, 5);
  const enabled = d.providers.filter((p) => p.enabled);
  const resting = enabled.filter((p) => p.circuit_open_until && Date.parse(p.circuit_open_until) > Date.now());
  const working = enabled.filter((p) => p.last_success_at);
  return (
    <section aria-labelledby="health-title">
      <h2 id="health-title" className="section-title mb-3">Studio health</h2>
      <dl className="divide-y divide-line rounded-xl border border-line bg-surface text-sm">
        <Row label="AI writers">
          {working.length} of {enabled.length} answered recently{resting.length ? `, ${resting.length} resting after limits or errors` : ""}
        </Row>
        <Row label="X spending">
          <span className="tabular">${d.spent.toFixed(3)}</span> of <span className="tabular">${d.cap.toFixed(2)}</span> this month
          <span className="mt-1.5 block h-1.5 w-full overflow-hidden rounded-full bg-sunken">
            <span className="block h-full bg-ink" style={{ width: `${Math.min(100, (d.spent / d.cap) * 100)}%` }} />
          </span>
        </Row>
        <Row label="Problems this week">
          {problems.length === 0 ? "None" : (
            <>
              <ul className="space-y-1.5">{problems.map((f) => {
                const fix = fixFor(f.error_message);
                return <li key={f.id}><span className="font-medium">{f.job_type.replace(/_/g, " ")}</span>: {String(f.error_message ?? "").slice(0, 90)}
                  {fix && <Link to={fix.to} className="ml-1 text-xs font-medium text-pixel hover:underline">{fix.label}</Link>}</li>;
              })}</ul>
              <div className="mt-2"><ClearButton title="Clear this week's problems?" done="Problems cleared" className="btn-quiet px-2.5 py-1 text-xs"
                body="These problems are hidden from this list. New ones still show, and the Activity page keeps the full history. You can undo this."
                onClear={() => cleared.clear("rundown_problems")} /></div>
            </>
          )}
        </Row>
      </dl>
    </section>
  );
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="grid grid-cols-[8.5rem_1fr] gap-3 px-4 py-3">
      <dt className="text-muted">{label}</dt>
      <dd>{children}</dd>
    </div>
  );
}
