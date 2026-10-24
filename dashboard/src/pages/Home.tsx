import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronLeft, ChevronRight, Pause, Play } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";
import ClearButton from "../components/ClearButton";
import Rundown from "../components/Rundown";
import { Confirm, ErrorNote, HostTag, Loading, PageHeader, StatusBadge, useToast } from "../components/ui";
import { must, useAccounts, useSaveSetting, useSetting, useTimezone } from "../lib/api";
import { useCleared, visibleAfterClear } from "../lib/clear";
import { fixFor } from "../lib/labels";
import { localDay, weekDays } from "../lib/format";
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
  const posts = useQuery({
    queryKey: ["posts", days[0]],
    queryFn: async () => {
      const from = new Date(Date.parse(`${days[0]}T00:00:00Z`) - 86_400_000).toISOString();
      const to = new Date(Date.parse(`${days[6]}T23:59:59Z`) + 86_400_000).toISOString();
      return (await must(supabase.from("scheduled_posts").select(POST_SELECT).gte("scheduled_at", from).lte("scheduled_at", to).neq("status", "cancelled"))) as unknown as Post[];
    },
  });
  const waiting = useQuery({
    queryKey: ["waiting"],
    queryFn: async () =>
      (await must(supabase.from("content_projects").select("id, title, status, channel_slug, format, parent_project_id, quality_report")
        .in("status", ["ready_for_review", "needs_attention"]).is("parent_project_id", null).order("created_at", { ascending: false }).limit(8))) as Project[],
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
      <PageHeader
        title="This week on air"
        intro={summaryLine(counts)}
        actions={<PauseButton />}
      />
      <section aria-labelledby="rundown-title" className="mb-10">
        <div className="mb-3 flex items-center justify-between gap-3">
          <h2 id="rundown-title" className="section-title">Rundown</h2>
          <WeekPicker offset={offset} setOffset={setOffset} />
        </div>
        <ErrorNote error={posts.error || accounts.error} />
        {accounts.isLoading || posts.isLoading ? <Loading /> : (
          <Rundown accounts={accounts.data ?? []} posts={week} days={days} tz={tz} today={localDay(new Date(), tz)} />
        )}
        <p className="mt-2 flex flex-wrap gap-x-5 gap-y-1 text-xs text-muted">
          <span className="inline-flex items-center gap-1.5"><HostTag channel="ai" /> AI topics</span>
          <span className="inline-flex items-center gap-1.5"><HostTag channel="money" /> Money topics</span>
          <span>Dashed outline: waiting for your approval</span>
          <span>Red outline: needs attention</span>
        </p>
      </section>

      <div className="grid grid-cols-1 gap-10 lg:grid-cols-[1.3fr_1fr]">
        <section aria-labelledby="waiting-title" className="min-w-0">
          <div className="mb-3 flex items-center justify-between">
            <h2 id="waiting-title" className="section-title">Waiting for you</h2>
            <Link to="/review" className="btn-quiet">Open Review Studio</Link>
          </div>
          {waiting.isLoading ? <Loading /> : (waiting.data ?? []).length === 0 ? (
            <p className="text-sm text-muted">Nothing to review. New videos arrive on Sunday evening.</p>
          ) : (
            <ul className="divide-y divide-line rounded-xl border border-line bg-surface">
              {(waiting.data ?? []).map((p) => (
                <li key={p.id}>
                  <Link to={`/review/${p.id}`} className="flex items-center gap-3 px-4 py-3 hover:bg-sunken">
                    <HostTag channel={p.channel_slug} />
                    <span className="min-w-0 flex-1 truncate text-sm font-medium">{p.title}</span>
                    <StatusBadge status={p.status} />
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </section>
        <div className="min-w-0 space-y-10">
          <ManualTasks />
          <Health />
        </div>
      </div>
    </>
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

function PauseButton() {
  const paused = useSetting<boolean>("paused", false).data ?? false;
  const save = useSaveSetting();
  const toast = useToast();
  const [ask, setAsk] = useState(false);
  return (
    <>
      <button className={paused ? "btn-primary" : "btn-danger"} onClick={() => setAsk(true)}>
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
          save.mutate({ key: "paused", value: !paused }, { onSuccess: () => toast(paused ? "Publishing resumed" : "Publishing paused") });
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
      const url = await signedUrl(storageKey, 600);
      if (url) window.location.href = url; else toast("That file has expired. Ask for a new render from Review Studio.", "bad");
    }}>Download video</button>
  );
}

function Health() {
  const health = useQuery({
    queryKey: ["health"],
    queryFn: async () => {
      const since = new Date(Date.now() - 7 * 86_400_000).toISOString();
      const [failed, providers, budget, reservations] = await Promise.all([
        must(supabase.from("generation_jobs").select("id, job_type, error_message, status, updated_at").in("status", ["failed", "blocked"]).gte("created_at", since).order("updated_at", { ascending: false }).limit(20)),
        must(supabase.from("ai_providers").select("name, enabled, last_error, last_success_at, circuit_open_until")),
        must(supabase.from("budgets").select("monthly_cap_usd").eq("service", "x_api")),
        must(supabase.from("budget_reservations").select("amount_usd, status").eq("service", "x_api").eq("month", new Date().toISOString().slice(0, 7) + "-01")),
      ]);
      return { failed: failed as any[], providers: providers as any[], cap: Number((budget as any[])[0]?.monthly_cap_usd ?? 1), spent: (reservations as any[]).filter((r) => r.status === "committed").reduce((a, r) => a + Number(r.amount_usd), 0) };
    },
  });
  const cleared = useCleared();
  if (health.isLoading) return <Loading />;
  const d = health.data;
  if (!d) return <ErrorNote error={health.error} />;
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
