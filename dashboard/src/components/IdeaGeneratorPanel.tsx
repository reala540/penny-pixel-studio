import { Lightbulb, RefreshCw, Sparkles, TriangleAlert } from "lucide-react";
import { Link } from "react-router-dom";
import { useSetting } from "../lib/api";
import { DEFAULT_IDEA_CONFIG } from "../lib/ideas";
import { useActiveIdeaJob, useIdeaActions, useIdeaRuns, useIdeas } from "../lib/ideasApi";
import { workerUrl } from "../lib/supabase";
import type { IdeaGeneratorConfig } from "../lib/types";
import IdeaCard from "./IdeaCard";
import { ErrorNote, Loading, useToast } from "./ui";

function ago(iso: string): string {
  const m = Math.max(0, Math.round((Date.now() - Date.parse(iso)) / 60000));
  return m < 1 ? "just now" : m < 60 ? `${m} min ago` : m < 1440 ? `${Math.floor(m / 60)} h ago` : new Date(iso).toLocaleDateString();
}

export default function IdeaGeneratorPanel() {
  const toast = useToast();
  const job = useActiveIdeaJob();
  const active = Boolean(job.data);
  const runs = useIdeaRuns(1, active);
  const latest = runs.data?.[0];
  const ideas = useIdeas({ runId: latest?.id ?? "", limit: 30 }, active);
  const cfg = { ...DEFAULT_IDEA_CONFIG, ...(useSetting<Partial<IdeaGeneratorConfig>>("idea_generator", {}).data ?? {}) };
  const check = useSetting<{ results?: { status: string }[] } | null>("provider_check", null).data;
  const working = check?.results ? check.results.filter((r) => r.status === "ok").length : null;
  const { generate } = useIdeaActions();
  const visible = (ideas.data ?? []).filter((i) => i.status !== "rejected").slice(0, cfg.count);

  const start = (trigger: "manual" | "regenerate") => generate.mutate(trigger, {
    onSuccess: () => toast(workerUrl ? "Idea research started. Ideas appear here in about 5–10 minutes." :
      "Queued. Without the Worker it starts at the next 15-minute check."),
    onError: (e) => toast((e as Error).message, "bad"),
  });

  return (
    <section className="mt-4 rounded-none border border-[color:var(--cr-line)] bg-[color:var(--cr-surface)] p-4" aria-labelledby="ideagen-title">
      <div className="flex flex-wrap items-start gap-3">
        <Lightbulb size={18} className="mt-1 shrink-0 text-[color:var(--cr-accent)]" aria-hidden />
        <div className="min-w-0 flex-1">
          <h2 id="ideagen-title" className="text-sm font-semibold text-[color:var(--cr-ink)]">AI Idea Generator</h2>
          <p className="mt-1 max-w-3xl text-xs leading-5 text-[color:var(--cr-muted)]">
            Researches your configured sources, then ranks ideas: 70% current trend evidence (measured from real, dated
            sources), 30% an independent AI assessment. Ideas go to your library; nothing is produced until you send one to the Studio and approve it.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          {latest && <button className="btn-quiet" onClick={() => start("regenerate")} disabled={active || generate.isPending || working === 0}><RefreshCw size={14} aria-hidden />Regenerate</button>}
          <button className="btn-primary" onClick={() => start("manual")} disabled={active || generate.isPending || working === 0}>
            <Sparkles size={14} aria-hidden />Generate {cfg.count} Ideas
          </button>
        </div>
      </div>

      {working === 0 && (
        <p role="alert" className="mt-3 flex items-start gap-2 rounded-lg bg-alert-soft px-3 py-2 text-sm text-alert">
          <TriangleAlert size={16} className="mt-0.5 shrink-0" aria-hidden />
          Configuration required: no AI provider passed the last key check. Add or fix keys in <Link to="/api" className="underline">AI APIs</Link>, then run First-time setup (keys only).
        </p>
      )}
      <div className="mt-3 text-xs text-[color:var(--cr-muted)]" aria-live="polite">
        {job.data ? (job.data.status === "queued" ? "Queued: the research run starts within a few minutes…" : "Researching sources and ranking ideas…")
          : latest ? <>
            Last run {ago(latest.started_at)} · {latest.produced_count} of {latest.requested_count} ideas · {latest.evidence_count} sources considered
            {latest.status === "failed" && <span className="text-alert"> · failed: {latest.error}</span>}
          </> : "No ideas yet. Press the button to run the first research batch."}
      </div>
      {latest?.notes?.length ? (
        <ul className="mt-2 list-disc space-y-0.5 pl-5 text-xs text-[color:var(--cr-muted)]">
          {latest.notes.slice(0, 4).map((n) => <li key={n}>{n}</li>)}
        </ul>
      ) : null}

      <ErrorNote error={runs.error || ideas.error} />
      {ideas.isLoading && latest ? <Loading label="Loading ideas" /> : visible.length > 0 && (
        <div className="mt-4 space-y-3">
          {visible.map((i) => <IdeaCard key={i.id} idea={i} />)}
          <Link to="/ideas" className="inline-block text-sm text-[color:var(--cr-accent)] underline-offset-4 hover:underline">Open the Idea Library</Link>
        </div>
      )}
    </section>
  );
}
