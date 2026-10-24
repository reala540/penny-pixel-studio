import { useQuery } from "@tanstack/react-query";
import { ArrowRight, CircleAlert, CircleCheck, Info, LoaderCircle } from "lucide-react";
import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import ClearButton from "../components/ClearButton";
import { Empty, ErrorNote, Loading, PageHeader } from "../components/ui";
import { buildTimeline, Category, inFilter, Item, jobTitle, useRunningJobs, type AuditRow, type JobRow, type NoteRow } from "../lib/activity";
import { must, useTimezone } from "../lib/api";
import { useCleared, visibleAfterClear } from "../lib/clear";
import { fixFor } from "../lib/labels";
import { supabase } from "../lib/supabase";

const FILTERS: [Category | "all" | "errors", string][] = [
  ["all", "Everything"], ["ideas", "Ideas"], ["research", "Research"], ["production", "Making videos"],
  ["review", "Review"], ["posting", "Posting"], ["errors", "Problems"],
];

function when(iso: string, tz: string): string {
  return new Date(iso).toLocaleString("en-GB", { timeZone: tz, weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
}

function startOfToday(tz: string): string {
  const day = new Intl.DateTimeFormat("en-CA", { timeZone: tz, year: "numeric", month: "2-digit", day: "2-digit" }).format(new Date());
  // midnight in the studio timezone, as UTC (close enough for a daily count)
  const probe = new Date(`${day}T00:00:00Z`);
  const shown = new Date(probe.toLocaleString("en-US", { timeZone: tz }));
  return new Date(probe.getTime() - (shown.getTime() - probe.getTime())).toISOString();
}

export default function Activity() {
  const tz = useTimezone();
  const [filter, setFilter] = useState<Category | "all" | "errors">("all");
  const cleared = useCleared();
  const running = useRunningJobs();
  const feed = useQuery({
    queryKey: ["activity-feed"],
    refetchInterval: 15_000,
    queryFn: async () => {
      const [jobs, notes, audits] = await Promise.all([
        must(supabase.from("generation_jobs").select("id, job_type, status, progress, input, error_message, requested_by, created_at, started_at, finished_at, updated_at, content_projects(title)")
          .in("status", ["completed", "failed"]).order("updated_at", { ascending: false }).limit(120)),
        must(supabase.from("notifications").select("id, kind, title, body, link, created_at, error").order("created_at", { ascending: false }).limit(150)),
        must(supabase.from("audit_logs").select("id, actor, action, details, created_at")
          .in("action", ["auto_review_post_on", "auto_review_post_off", "posting_schedule_changed", "setup_value_saved", "setup_value_removed", "paused", "resumed", "telegram_linked"])
          .order("created_at", { ascending: false }).limit(60)),
      ]);
      return buildTimeline(jobs as unknown as JobRow[], notes as NoteRow[], audits as AuditRow[]);
    },
  });
  const today = useToday(tz);
  const items = useMemo(() => visibleAfterClear(feed.data ?? [], cleared.map, "activity", (i) => i.at), [feed.data, cleared.map]);
  const shown = items.filter((i) => inFilter(i, filter));

  return (
    <>
      <PageHeader title="Activity" intro="Everything the studio is doing and has done, in plain words. Problems come with a button that takes you to the fix."
        actions={<ClearButton label="Clear history" title="Clear the activity history?" done="Activity history cleared"
          disabled={!items.length}
          body={<>This hides the {items.length} event{items.length === 1 ? "" : "s"} listed now. Work in progress stays, new events keep appearing, and the audit log is never cleared. You can undo this.</>}
          onClear={() => cleared.clear("activity")} />} />

      <HowItWorks />

      <section aria-labelledby="now-title" className="mb-8">
        <h2 id="now-title" className="section-title mb-3">Running now</h2>
        <ErrorNote error={running.error} />
        {running.isLoading ? <Loading /> : (running.data ?? []).length === 0 ? (
          <p className="rounded-xl border border-dashed border-line px-4 py-3 text-sm text-muted">Nothing is running. The studio is idle until the next scheduled run or until you start something.</p>
        ) : (
          <ul className="space-y-2">
            {(running.data ?? []).map((j) => <RunningRow key={j.id} job={j} tz={tz} />)}
          </ul>
        )}
      </section>

      <section aria-labelledby="today-title" className="mb-8">
        <h2 id="today-title" className="section-title mb-3">Today so far</h2>
        <dl className="grid grid-cols-2 gap-2 sm:grid-cols-5">
          {([["Ideas found", today.data?.ideas], ["Videos made", today.data?.videos], ["Approved", today.data?.approved],
            ["Posted", today.data?.posted], ["Problems", today.data?.problems]] as const).map(([label, n]) => (
            <div key={label} className="rounded-xl border border-line bg-surface px-4 py-3">
              <dt className="text-xs text-muted">{label}</dt>
              <dd className={`font-display text-2xl font-bold tabular ${label === "Problems" && n ? "text-alert" : ""}`}>{n ?? "–"}</dd>
            </div>
          ))}
        </dl>
      </section>

      <section aria-labelledby="timeline-title">
        <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
          <h2 id="timeline-title" className="section-title">Timeline</h2>
          <div role="tablist" aria-label="Show" className="flex flex-wrap gap-1">
            {FILTERS.map(([v, label]) => (
              <button key={v} role="tab" aria-selected={filter === v} onClick={() => setFilter(v)}
                className={`rounded-lg px-3 py-1.5 text-sm ${filter === v ? "bg-ink text-surface" : "text-muted hover:bg-sunken hover:text-ink"}`}>{label}</button>
            ))}
          </div>
        </div>
        <ErrorNote error={feed.error} />
        {feed.isLoading ? <Loading /> : shown.length === 0 ? (
          <Empty title={filter === "errors" ? "No problems" : "Nothing here yet"}>
            {filter === "errors" ? "Everything that ran recently worked." : "Events appear here as the studio works: ideas, research, videos, reviews and posts."}
          </Empty>
        ) : (
          <ol className="divide-y divide-line rounded-xl border border-line bg-surface">
            {shown.slice(0, 150).map((i) => <TimelineRow key={i.id} item={i} tz={tz} />)}
          </ol>
        )}
      </section>
    </>
  );
}

function RunningRow({ job, tz }: { job: JobRow; tz: string }) {
  const p = job.progress;
  const pct = p?.step && p?.total ? Math.round((p.step / p.total) * 100) : null;
  return (
    <li className="rounded-xl border border-line bg-surface px-4 py-3">
      <div className="flex items-center gap-2">
        <LoaderCircle size={16} className={job.status === "running" ? "animate-spin text-pixel" : "text-muted"} aria-hidden />
        <span className="text-sm font-medium">{jobTitle(job)}</span>
        <span className="ml-auto text-xs text-muted">{job.status === "queued" ? `Waiting to start · asked ${when(job.created_at, tz)}` : `Started ${when(job.started_at ?? job.updated_at, tz)}`}</span>
      </div>
      {job.status === "running" && (
        <>
          <p className="mt-1 text-sm text-muted">{p?.label ?? "Working…"}</p>
          {pct !== null && (
            <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-sunken" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={pct} aria-label="Progress">
              <span className="block h-full bg-pixel" style={{ width: `${pct}%` }} />
            </div>
          )}
        </>
      )}
      {job.status === "queued" && <p className="mt-1 text-xs text-muted">The engine picks this up within a few minutes (at most 15).</p>}
    </li>
  );
}

function TimelineRow({ item, tz }: { item: Item; tz: string }) {
  const Icon = item.tone === "bad" ? CircleAlert : item.tone === "good" ? CircleCheck : Info;
  const fix = item.error ? fixFor(`${item.title} ${item.detail ?? ""}`) : null;
  const internal = item.link && item.link.includes("/review/") ? `/review/${item.link.split("/review/")[1]}` : null;
  return (
    <li className="flex gap-3 px-4 py-3">
      <Icon size={17} className={`mt-0.5 shrink-0 ${item.tone === "bad" ? "text-alert" : item.tone === "good" ? "text-penny" : "text-muted"}`} aria-hidden />
      <div className="min-w-0 flex-1">
        <p className="text-sm font-medium">{item.title}</p>
        {item.detail && <p className="mt-0.5 line-clamp-3 text-sm text-muted">{item.detail}</p>}
        <div className="mt-1 flex flex-wrap items-center gap-3 text-xs text-muted">
          <time dateTime={item.at}>{when(item.at, tz)}</time>
          {fix && <Link to={fix.to} className="inline-flex items-center gap-1 rounded-md bg-alert-soft px-2 py-0.5 font-medium text-alert hover:underline">{fix.label}<ArrowRight size={12} aria-hidden /></Link>}
          {!fix && internal && <Link to={internal} className="text-pixel hover:underline">Open</Link>}
        </div>
      </div>
    </li>
  );
}

function useToday(tz: string) {
  return useQuery({
    queryKey: ["activity-today", tz],
    refetchInterval: 60_000,
    queryFn: async () => {
      const since = startOfToday(tz);
      const count = async (q: PromiseLike<{ count: number | null; error: { message: string } | null }>) => {
        const { count: n, error } = await q;
        if (error) throw new Error(error.message);
        return n ?? 0;
      };
      const [ideas, videos, approved, posted, failedJobs, failedPosts] = await Promise.all([
        count(supabase.from("generated_ideas").select("id", { count: "exact", head: true }).gte("created_at", since)),
        count(supabase.from("content_projects").select("id", { count: "exact", head: true }).eq("format", "long").gte("created_at", since)),
        count(supabase.from("approvals").select("id", { count: "exact", head: true }).eq("decision", "approved").eq("target_type", "project").gte("decided_at", since)),
        count(supabase.from("published_posts").select("id", { count: "exact", head: true }).gte("published_at", since)),
        count(supabase.from("generation_jobs").select("id", { count: "exact", head: true }).eq("status", "failed").gte("updated_at", since)),
        count(supabase.from("scheduled_posts").select("id", { count: "exact", head: true }).in("status", ["failed", "blocked", "needs_review"]).gte("updated_at", since)),
      ]);
      return { ideas, videos, approved, posted, problems: failedJobs + failedPosts };
    },
  });
}

const STAGES: { label: string; to: string; explain: string }[] = [
  { label: "Ideas", to: "/ideas", explain: "Find topics people care about now" },
  { label: "Research", to: "/research", explain: "Collect dated sources and facts" },
  { label: "Write", to: "/activity", explain: "Script in the host's voice" },
  { label: "Check", to: "/activity", explain: "Facts, quality, freshness, licences" },
  { label: "Review", to: "/review", explain: "You (or Auto Review) approve" },
  { label: "Post", to: "/calendar", explain: "Goes out at its scheduled time" },
];

function HowItWorks() {
  const counts = useQuery({
    queryKey: ["flow-counts"],
    refetchInterval: 30_000,
    queryFn: async () => {
      const c = async (q: PromiseLike<{ count: number | null; error: { message: string } | null }>) => (await q).count ?? 0;
      const [ideas, research, writing, checking, review, post] = await Promise.all([
        c(supabase.from("generated_ideas").select("id", { count: "exact", head: true }).in("status", ["new", "saved"])),
        c(supabase.from("content_ideas").select("id", { count: "exact", head: true }).in("status", ["shortlisted", "selected"])),
        c(supabase.from("content_projects").select("id", { count: "exact", head: true }).eq("status", "scripting")),
        c(supabase.from("content_projects").select("id", { count: "exact", head: true }).in("status", ["verifying", "rendering"])),
        c(supabase.from("content_projects").select("id", { count: "exact", head: true }).in("status", ["ready_for_review", "needs_attention"]).is("parent_project_id", null)),
        c(supabase.from("scheduled_posts").select("id", { count: "exact", head: true }).eq("status", "scheduled")),
      ]);
      return [ideas, research, writing, checking, review, post];
    },
  });
  return (
    <section aria-labelledby="flow-title" className="mb-8 rounded-xl border border-line bg-surface p-4">
      <h2 id="flow-title" className="text-sm font-semibold">How the studio works</h2>
      <p className="mt-1 text-xs text-muted">Each piece of work moves left to right. The numbers show how many are at each step right now.</p>
      <ol className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-6">
        {STAGES.map((s, i) => (
          <li key={s.label}>
            <Link to={s.to} className="block h-full rounded-lg border border-line px-3 py-2 hover:bg-sunken">
              <span className="flex items-baseline justify-between gap-2">
                <span className="text-sm font-medium">{i + 1}. {s.label}</span>
                <span className="font-display text-lg font-bold tabular">{counts.data?.[i] ?? "–"}</span>
              </span>
              <span className="block text-xs text-muted">{s.explain}</span>
            </Link>
          </li>
        ))}
      </ol>
    </section>
  );
}
