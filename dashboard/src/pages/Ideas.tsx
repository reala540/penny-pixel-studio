import { Sparkles } from "lucide-react";
import { useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import ClearButton from "../components/ClearButton";
import IdeaCard from "../components/IdeaCard";
import { Empty, ErrorNote, Loading, PageHeader, useToast } from "../components/ui";
import { must, useSetting } from "../lib/api";
import { useCleared, visibleAfterClear } from "../lib/clear";
import { supabase } from "../lib/supabase";
import { DEFAULT_IDEA_CONFIG } from "../lib/ideas";
import { useActiveIdeaJob, useIdeaActions, useIdeaRuns, useIdeas } from "../lib/ideasApi";
import type { IdeaGeneratorConfig, IdeaStatus } from "../lib/types";

const TABS: [IdeaStatus | "all", string][] = [
  ["all", "All"], ["new", "New"], ["saved", "Saved"], ["sent_to_studio", "Sent to Studio"], ["rejected", "Rejected"], ["archived", "Archived"],
];

export default function Ideas() {
  const toast = useToast();
  const [tab, setTab] = useState<IdeaStatus | "all">("all");
  const [q, setQ] = useState("");
  const [sort, setSort] = useState<"score" | "newest">("newest");
  const job = useActiveIdeaJob();
  const ideas = useIdeas({ status: tab, limit: 300 }, Boolean(job.data));
  const runs = useIdeaRuns(12, Boolean(job.data));
  const cfg = { ...DEFAULT_IDEA_CONFIG, ...(useSetting<Partial<IdeaGeneratorConfig>>("idea_generator", {}).data ?? {}) };
  const { generate } = useIdeaActions();
  const qc = useQueryClient();
  const cleared = useCleared();
  const history = visibleAfterClear(runs.data ?? [], cleared.map, "idea_runs", (r) => r.started_at);
  const filtered = tab !== "all" || q.trim() !== "" || sort !== "newest";

  /** Moves every unsaved "New" idea to Archived; Undo puts exactly those back. */
  async function archiveNew() {
    const rows = (await must(supabase.from("generated_ideas").select("id").eq("status", "new").limit(1000))) as { id: string }[];
    const ids = rows.map((r) => r.id);
    if (!ids.length) throw new Error("There are no new ideas to clear.");
    await must(supabase.from("generated_ideas").update({ status: "archived" }).in("id", ids));
    qc.invalidateQueries({ queryKey: ["ideas"] });
    return async () => {
      await must(supabase.from("generated_ideas").update({ status: "new" }).in("id", ids).eq("status", "archived"));
      qc.invalidateQueries({ queryKey: ["ideas"] });
    };
  }

  const shown = useMemo(() => {
    const needle = q.trim().toLowerCase();
    const list = (ideas.data ?? []).filter((i) => !needle || `${i.title} ${i.summary} ${i.category ?? ""}`.toLowerCase().includes(needle));
    return sort === "score" ? [...list].sort((a, b) => Number(b.total) - Number(a.total)) : list;
  }, [ideas.data, q, sort]);

  return (
    <>
      <PageHeader title="Idea Library" intro="Every generated idea with its evidence, score and history. Save the good ones, reject the rest; rejected ideas are never suggested again."
        actions={<>
          <ClearButton label="Clear new ideas" title="Clear all new ideas?" done="New ideas moved to Archived"
            body="Every idea still marked New (not saved, sent or rejected) moves to Archived, so the next batch starts clean. Nothing is deleted, and Undo puts them back."
            onClear={archiveNew} />
          <button className="btn-primary" disabled={Boolean(job.data) || generate.isPending}
            onClick={() => generate.mutate("manual", { onSuccess: () => toast("Idea research started."), onError: (e) => toast((e as Error).message, "bad") })}>
            <Sparkles size={14} aria-hidden />{job.data ? "Generating…" : `Generate ${cfg.count} Ideas`}</button>
        </>} />

      <div className="mb-4 flex flex-wrap items-center gap-3">
        <div role="tablist" aria-label="Filter by status" className="flex flex-wrap gap-1">
          {TABS.map(([v, label]) => (
            <button key={v} role="tab" aria-selected={tab === v} onClick={() => setTab(v)}
              className={`rounded-lg px-3 py-1.5 text-sm ${tab === v ? "bg-ink text-surface" : "text-muted hover:bg-sunken hover:text-ink"}`}>{label}</button>
          ))}
        </div>
        <label className="ml-auto min-w-[12rem] flex-1 sm:max-w-xs"><span className="sr-only">Search ideas</span>
          <input className="field" type="search" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search ideas" />
        </label>
        <label className="flex items-center gap-2 text-sm text-muted">Sort
          <select aria-label="Sort" className="field w-auto" value={sort} onChange={(e) => setSort(e.target.value as "score" | "newest")}>
            <option value="newest">Newest</option><option value="score">Highest score</option>
          </select>
        </label>
        {filtered && <button className="btn-quiet" onClick={() => { setTab("all"); setQ(""); setSort("newest"); }}>Clear filters</button>}
      </div>

      <ErrorNote error={ideas.error} />
      <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_320px]">
        <div className="min-w-0 space-y-3">
          {ideas.isLoading ? <Loading label="Loading ideas" /> : shown.length === 0
            ? <Empty title="No ideas here yet">Generate a batch, or change the filter.</Empty>
            : shown.map((i) => <IdeaCard key={i.id} idea={i} />)}
        </div>
        <aside aria-labelledby="runs-title">
          <div className="flex items-center justify-between gap-2">
            <h2 id="runs-title" className="section-title text-base">Generation history</h2>
            {history.length > 0 && <ClearButton title="Clear the generation history?" done="History cleared" className="btn-quiet px-2.5 py-1 text-xs"
              body="This hides the runs listed here. The ideas stay in the library. You can undo this." onClear={() => cleared.clear("idea_runs")} />}
          </div>
          {runs.isLoading ? <Loading /> : history.length === 0 ? <p className="mt-2 text-sm text-muted">No runs yet.</p> : (
            <ul className="mt-3 divide-y divide-line rounded-xl border border-line bg-surface">
              {history.map((r) => (
                <li key={r.id} className="px-4 py-3 text-sm">
                  <div className="flex items-center justify-between gap-2">
                    <span className="font-medium text-ink">{new Date(r.started_at).toLocaleString()}</span>
                    <span className={`text-xs ${r.status === "failed" ? "text-alert" : r.status === "partial" ? "text-ink" : "text-muted"}`}>{r.status}</span>
                  </div>
                  <p className="text-xs text-muted">{r.trigger} · {r.produced_count}/{r.requested_count} ideas · {r.evidence_count} sources</p>
                  {r.error && <p className="mt-1 text-xs text-alert">{r.error}</p>}
                  {r.notes?.slice(0, 2).map((n) => <p key={n} className="mt-1 text-xs text-muted">{n}</p>)}
                </li>
              ))}
            </ul>
          )}
        </aside>
      </div>
    </>
  );
}
