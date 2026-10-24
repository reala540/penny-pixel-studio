import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import ClearButton from "../components/ClearButton";
import { Empty, ErrorNote, HostTag, Loading, PageHeader, StatusBadge, useToast } from "../components/ui";
import { must } from "../lib/api";
import { isCleared, useCleared } from "../lib/clear";
import { safeUrl } from "../lib/format";
import { supabase } from "../lib/supabase";
import type { Channel, Idea } from "../lib/types";

const FACTORS: [string, string][] = [
  ["originality", "Original"],
  ["evidence", "Evidence"],
  ["audience_relevance", "Audience fit"],
  ["search_demand", "Search demand"],
  ["trend_momentum", "Trending"],
  ["freshness", "Fresh"],
];

export default function Research() {
  const [channel, setChannel] = useState<"all" | Channel>("all");
  const qc = useQueryClient();
  const toast = useToast();
  const ideas = useQuery({
    queryKey: ["ideas"],
    queryFn: async () => (await must(supabase.from("content_ideas").select("*").order("batch_week", { ascending: false }).order("score", { ascending: false }).limit(120))) as Idea[],
  });
  const sources = useQuery({
    queryKey: ["sources-recent"],
    queryFn: async () => (await must(supabase.from("research_sources").select("id, title, publisher, url, published_at, credibility, topic").order("retrieved_at", { ascending: false }).limit(400))) as any[],
  });
  const setStatus = useMutation({
    mutationFn: async ({ id, status }: { id: string; status: string }) => must(supabase.from("content_ideas").update({ status }).eq("id", id)),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["ideas"] }); toast("Idea updated"); },
  });
  const cleared = useCleared();
  // "Clear old research" hides past ideas; anything shortlisted or being made always stays.
  const keep = (i: Idea) => ["shortlisted", "selected"].includes(i.status) || !isCleared(cleared.map, "research", i.created_at);
  const list = (ideas.data ?? []).filter((i) => (channel === "all" || i.channel_slug === channel) && keep(i));
  const hidden = (ideas.data ?? []).filter((i) => !keep(i)).length;
  const byId = new Map((sources.data ?? []).map((s) => [s.id, s]));
  const weeks = [...new Set(list.map((i) => i.batch_week ?? ""))];

  return (
    <>
      <PageHeader title="Research" intro="Ideas found on Saturday, scored on evidence, originality and demand. Shortlisted ideas are produced on Sunday."
        actions={<ClearButton label="Clear old research" title="Clear old research from this page?" done="Old research cleared" disabled={!list.length}
          body="Ideas found so far leave this page, except ones shortlisted or being made. Their sources stay saved, because published videos cite them. New research appears as usual. You can undo this."
          onClear={() => cleared.clear("research")} />} />
      {hidden > 0 && <p className="-mt-3 mb-4 text-xs text-muted">{hidden} older idea{hidden === 1 ? "" : "s"} cleared from view.</p>}
      <div role="radiogroup" aria-label="Channel" className="mb-6 flex gap-1">
        {([["all", "Both channels"], ["ai", "Pixel · AI"], ["money", "Penny · Money"]] as const).map(([k, label]) => (
          <button key={k} role="radio" aria-checked={channel === k} onClick={() => setChannel(k)} className={channel === k ? "btn-primary" : "btn-quiet"}>{label}</button>
        ))}
      </div>
      <ErrorNote error={ideas.error} />
      {ideas.isLoading ? <Loading /> : list.length === 0 ? (
        <Empty title="No ideas yet">Research runs every Saturday morning. To run it now, go to Settings → Run now → Research.</Empty>
      ) : weeks.map((w) => (
        <section key={w} className="mb-10" aria-label={`Week of ${w}`}>
          <h2 className="section-title mb-3">Week of {w ? new Date(`${w}T12:00:00Z`).toLocaleDateString("en-GB", { day: "numeric", month: "long" }) : "unknown"}</h2>
          <ol className="space-y-3">
            {list.filter((i) => (i.batch_week ?? "") === w).map((i) => (
              <li key={i.id} className="rounded-xl border border-line bg-surface p-4">
                <div className="grid gap-4 md:grid-cols-[1fr_220px]">
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <HostTag channel={i.channel_slug} />
                      <StatusBadge status={i.status} />
                      {i.is_experiment && <span className="rounded-md bg-sunken px-2 py-0.5 text-xs text-muted">Experiment</span>}
                    </div>
                    <h3 className="mt-2 font-display text-lg font-semibold leading-snug">{i.title}</h3>
                    {i.angle && <p className="mt-1 text-sm text-muted">{i.angle}</p>}
                    {i.explanation && <p className="mt-2 text-sm">{i.explanation}</p>}
                    <ul className="mt-3 space-y-1">
                      {i.source_ids.map((sid) => byId.get(sid)).filter(Boolean).map((s: any) => (
                        <li key={s.id} className="text-xs">
                          <a href={safeUrl(s.url)} target="_blank" rel="noreferrer" className="text-pixel underline-offset-2 hover:underline">{s.publisher ?? "Source"}: {s.title}</a>
                          <span className="text-muted"> · {s.credibility.replace(/_/g, " ")}{s.published_at ? ` · ${new Date(s.published_at).toLocaleDateString("en-GB")}` : ""}</span>
                        </li>
                      ))}
                    </ul>
                  </div>
                  <div>
                    <p className="flex items-baseline justify-between"><span className="text-sm text-muted">Score</span><span className="font-display text-2xl font-bold tabular">{Math.round(i.score)}</span></p>
                    <dl className="mt-2 space-y-1.5">
                      {FACTORS.map(([k, label]) => {
                        const v = Number(i.score_breakdown?.[k] ?? 0);
                        return (
                          <div key={k} className="text-xs">
                            <dt className="flex justify-between text-muted"><span>{label}</span><span className="tabular">{Math.round(v * 100)}</span></dt>
                            <dd className="mt-0.5 h-1.5 overflow-hidden rounded-full bg-sunken"><span className={`block h-full ${i.channel_slug === "ai" ? "bg-pixel" : "bg-penny"}`} style={{ width: `${v * 100}%` }} /></dd>
                          </div>
                        );
                      })}
                    </dl>
                    {["proposed", "saved", "shortlisted"].includes(i.status) && (
                      <div className="mt-3 flex flex-wrap gap-1.5">
                        {i.status !== "shortlisted" && <button className="btn-quiet px-2.5 py-1" onClick={() => setStatus.mutate({ id: i.id, status: "shortlisted" })}>Shortlist</button>}
                        {i.status !== "saved" && <button className="btn-quiet px-2.5 py-1" onClick={() => setStatus.mutate({ id: i.id, status: "saved" })}>Save for later</button>}
                        <button className="btn-quiet px-2.5 py-1" onClick={() => setStatus.mutate({ id: i.id, status: "rejected" })}>Drop</button>
                      </div>
                    )}
                  </div>
                </div>
              </li>
            ))}
          </ol>
        </section>
      ))}
    </>
  );
}
