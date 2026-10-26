import { Sparkles } from "lucide-react";
import { useQueryClient } from "@tanstack/react-query";
import { useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import ResearchIdeaCard from "../components/ResearchIdeaCard";
import { isCleared } from "../lib/clear";
import ClearButton from "../components/ClearButton";
import IdeaCard from "../components/IdeaCard";
import { Empty, ErrorNote, Loading, NotConfirmed, PageHeader, useToast } from "../components/ui";
import { must, useSetting } from "../lib/api";
import { useCleared, visibleAfterClear } from "../lib/clear";
import { supabase } from "../lib/supabase";
import { DEFAULT_IDEA_CONFIG } from "../lib/ideas";
import { useActiveIdeaJob, useIdeaActions, useIdeaRuns, useIdeas } from "../lib/ideasApi";
import type { Idea, IdeaGeneratorConfig, IdeaStatus } from "../lib/types";

const TABS: [IdeaStatus | "all", string][] = [
  ["all", "All"], ["new", "To use"], ["saved", "Saved"], ["sent_to_studio", "Used"], ["rejected", "Not for me"], ["archived", "Archived"],
];
/** Research idea statuses that match each tab. */
const RESEARCH_FOR: Record<IdeaStatus | "all", string[] | null> = {
  all: null, new: ["proposed", "shortlisted"], saved: ["saved"], sent_to_studio: ["selected", "produced"], rejected: ["rejected"], archived: ["expired"],
};

/** Content → Ideas: Idea Generator ideas and weekly research ideas in one list. */
export default function Ideas() {
  const toast = useToast();
  const [params, setParams] = useSearchParams();
  const navigate = useNavigate();
  const source = (params.get("source") ?? "both") as "both" | "generator" | "research";
  const setSource = (v: string) => { const p = new URLSearchParams(params); p.set("source", v); setParams(p, { replace: true }); };
  const [tab, setTab] = useState<IdeaStatus | "all">("all");
  const [q, setQ] = useState("");
  const [sort, setSort] = useState<"score" | "newest">("newest");
  const [page,setPage]=useState(0);
  useEffect(()=>setPage(0),[tab,q,sort,source]);
  const job = useActiveIdeaJob();
  const ideas = useIdeas({ status: tab, limit: 50, page, search: q, sort }, Boolean(job.data));
  const runs = useIdeaRuns(12, Boolean(job.data));
  const cfg = { ...DEFAULT_IDEA_CONFIG, ...(useSetting<Partial<IdeaGeneratorConfig>>("idea_generator", {}).data ?? {}) };
  const { generate } = useIdeaActions();
  const qc = useQueryClient();
  const cleared = useCleared();
  const history = visibleAfterClear(runs.data ?? [], cleared.map, "idea_runs", (r) => r.started_at);
  const filtered = tab !== "all" || q.trim() !== "" || sort !== "newest";
  const research = useQuery({
    queryKey: ["research-ideas", "library", tab, page, q, sort],
    enabled: source !== "generator",
    queryFn: async () => {
      let qy = supabase.from("content_ideas").select("*").order(sort === "score" ? "score" : "batch_week", { ascending: false }).order("id").range(page*50,page*50+49);
      const needle=q.replace(/[,%()]/g," ").trim();
      if(needle)qy=qy.or(`title.ilike.%${needle}%,angle.ilike.%${needle}%`);
      const st = RESEARCH_FOR[tab];
      if (st) qy = qy.in("status", st);
      return (await must(qy)) as Idea[];
    },
  });
  // "Clear old research" hides past research ideas; anything shortlisted or being made always stays.
  const keepResearch = (i: Idea) => ["shortlisted", "selected"].includes(i.status) || !isCleared(cleared.map, "research", i.created_at);
  const researchShown = (research.data ?? []).filter((i) => keepResearch(i) && (!q.trim() || `${i.title} ${i.angle ?? ""}`.toLowerCase().includes(q.trim().toLowerCase())));

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
      <PageHeader title="Ideas" intro="Every idea from the Idea Generator and the weekly research, with its evidence and score. Use one to create a package; ideas marked Not for me are never suggested again."
        actions={<>
          <ClearButton label="Clear new ideas" title="Clear all new ideas?" done="New ideas moved to Archived"
            body="Every idea still marked New (not saved, sent or rejected) moves to Archived, so the next batch starts clean. Nothing is deleted, and Undo puts them back."
            onClear={archiveNew} />
          <button className="btn-primary" disabled={Boolean(job.data) || generate.isPending}
            onClick={() => generate.mutate("manual", { onSuccess: () => toast("Idea research started."), onError: (e) => toast((e as Error).message, "bad") })}>
            <Sparkles size={14} aria-hidden />{job.data ? "Generating…" : `Generate ${cfg.count} Ideas`}</button>
        </>} />

      <nav aria-label="Idea pages" className="mb-3 flex items-center gap-3"><button className="btn-quiet" disabled={!page || ideas.isFetching || research.isFetching} onClick={()=>setPage((p)=>p-1)}>Previous</button><span className="text-sm">Page {page+1}</span><button className="btn-quiet" disabled={ideas.isFetching || research.isFetching || ((source === "research" || (ideas.data?.length??0)<50) && (source === "generator" || (research.data?.length??0)<50))} onClick={()=>setPage((p)=>p+1)}>Next</button></nav>
      <nav aria-label="Breadcrumb" className="-mt-3 mb-4 text-sm text-muted"><Link to="/content" className="hover:underline">Content</Link> › <span className="text-ink">Ideas</span></nav>
      <div className="mb-3 flex flex-wrap items-center gap-2 text-sm">
        <span className="text-muted">Source</span>
        <div role="radiogroup" aria-label="Source" className="flex gap-1">
          {([["both", "Both"], ["generator", "Idea Generator"], ["research", "Weekly research"]] as const).map(([v, label]) => (
            <button key={v} role="radio" aria-checked={source === v} onClick={() => setSource(v)}
              className={`rounded-lg border px-3 py-1 ${source === v ? "border-ink bg-ink text-surface" : "border-line text-muted hover:text-ink"}`}>{label}</button>
          ))}
        </div>
      </div>
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

      <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_320px]">
        <div className="min-w-0 space-y-3">
          {source !== "research" && (ideas.isLoading ? <Loading label="Loading ideas" /> : ideas.isError ? <NotConfirmed q={ideas} what="your ideas" /> : shown.length === 0
            ? (source === "generator" || researchShown.length === 0) && <Empty title="No ideas here yet">Generate a batch, or change the filter.</Empty>
            : shown.map((i) => <IdeaCard key={i.id} idea={i} />))}
          {source !== "generator" && (
            <section aria-labelledby="research-title" className={source === "both" ? "pt-4" : ""}>
              <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
                <h2 id="research-title" className="section-title text-base">Weekly research ideas</h2>
                {researchShown.length > 0 && <ClearButton label="Clear old research" title="Clear old research from this page?" done="Old research cleared" className="btn-quiet px-2.5 py-1 text-xs"
                  body="Research ideas found so far leave this list, except ones shortlisted or being made. Their sources stay saved, because videos cite them. You can undo this."
                  onClear={() => cleared.clear("research")} />}
              </div>
              {research.isLoading ? <Loading /> : research.isError ? <NotConfirmed q={research} what="research ideas" /> : researchShown.length === 0
                ? <p className="text-sm text-muted">No research ideas here. Weekly research runs on Saturday, or start it from Activity → Quick actions.</p>
                : <div className="space-y-3">{researchShown.map((i) => <ResearchIdeaCard key={i.id} idea={i}
                    onUse={() => navigate(`/create?step=research&kind=research&id=${i.id}&channel=${i.channel_slug}`)} useLabel="Create from this idea" />)}</div>}
            </section>
          )}
        </div>
        <aside aria-labelledby="runs-title">
          <div className="flex items-center justify-between gap-2">
            <h2 id="runs-title" className="section-title text-base">Generation history</h2>
            {history.length > 0 && <ClearButton title="Clear the generation history?" done="History cleared" className="btn-quiet px-2.5 py-1 text-xs"
              body="This hides the runs listed here. The ideas stay in the library. You can undo this." onClear={() => cleared.clear("idea_runs")} />}
          </div>
          {runs.isLoading ? <Loading /> : runs.isError ? <NotConfirmed q={runs} what="idea runs" /> : history.length === 0 ? <p className="mt-2 text-sm text-muted">No runs yet.</p> : (
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
