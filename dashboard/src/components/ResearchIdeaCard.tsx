import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Send } from "lucide-react";
import { must } from "../lib/api";
import { safeUrl } from "../lib/format";
import { supabase } from "../lib/supabase";
import type { Idea } from "../lib/types";
import { HostTag, StatusBadge, useToast } from "./ui";

const FACTORS: [string, string][] = [
  ["originality", "Original"], ["evidence", "Evidence"], ["audience_relevance", "Audience fit"],
  ["search_demand", "Search demand"], ["trend_momentum", "Trending"], ["freshness", "Fresh"],
];

/** A weekly-research idea: score breakdown, its sources, and Shortlist / Save for later / Drop. */
export default function ResearchIdeaCard({ idea, onUse, useLabel = "Use this idea", showSources = true }: {
  idea: Idea; onUse?: (idea: Idea) => void; useLabel?: string; showSources?: boolean;
}) {
  const qc = useQueryClient();
  const toast = useToast();
  const sources = useQuery({
    queryKey: ["idea-sources", idea.id],
    enabled: showSources && idea.source_ids.length > 0,
    queryFn: async () => (await must(supabase.from("research_sources").select("id, title, publisher, url, published_at, credibility").in("id", idea.source_ids))) as any[],
  });
  const setStatus = useMutation({
    mutationFn: async (status: string) => must(supabase.from("content_ideas").update({ status }).eq("id", idea.id)),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["ideas"] }); qc.invalidateQueries({ queryKey: ["research-ideas"] }); toast("Idea updated"); },
    onError: (e) => toast((e as Error).message, "bad"),
  });
  const open = ["proposed", "saved", "shortlisted"].includes(idea.status);
  return (
    <article className="rounded-xl border border-line bg-surface p-4" aria-labelledby={`ri-${idea.id}`}>
      <div className="grid gap-4 md:grid-cols-[1fr_200px]">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <span className="rounded-md bg-sunken px-2 py-0.5 text-xs text-muted">Weekly research</span>
            <HostTag channel={idea.channel_slug} />
            <StatusBadge status={idea.status} />
            {idea.is_experiment && <span className="rounded-md bg-sunken px-2 py-0.5 text-xs text-muted">Experiment</span>}
          </div>
          <h3 id={`ri-${idea.id}`} className="mt-2 font-display text-base font-semibold leading-snug">{idea.title}</h3>
          {idea.angle && <p className="mt-1 text-sm text-muted">{idea.angle}</p>}
          {idea.explanation && <p className="mt-2 text-sm">{idea.explanation}</p>}
          {showSources && (
            <ul className="mt-3 space-y-1">
              {(sources.data ?? []).map((s) => (
                <li key={s.id} className="text-xs">
                  <a href={safeUrl(s.url)} target="_blank" rel="noreferrer" className="text-pixel underline-offset-2 hover:underline">{s.publisher ?? "Source"}: {s.title}</a>
                  <span className="text-muted"> · {String(s.credibility).replace(/_/g, " ")}{s.published_at ? ` · ${new Date(s.published_at).toLocaleDateString("en-GB")}` : ""}</span>
                </li>
              ))}
            </ul>
          )}
          <div className="mt-3 flex flex-wrap gap-1.5">
            {onUse && <button className="btn-primary" onClick={() => onUse(idea)} disabled={idea.status === "rejected"}><Send size={14} aria-hidden />{useLabel}</button>}
            {open && idea.status !== "shortlisted" && <button className="btn-quiet px-2.5 py-1" onClick={() => setStatus.mutate("shortlisted")} disabled={setStatus.isPending}>Shortlist</button>}
            {open && idea.status !== "saved" && <button className="btn-quiet px-2.5 py-1" onClick={() => setStatus.mutate("saved")} disabled={setStatus.isPending}>Save for later</button>}
            {open && <button className="btn-quiet px-2.5 py-1" onClick={() => setStatus.mutate("rejected")} disabled={setStatus.isPending}>Drop</button>}
          </div>
        </div>
        <div>
          <p className="flex items-baseline justify-between"><span className="text-sm text-muted">Score</span><span className="font-display text-2xl font-bold tabular">{Math.round(idea.score)}</span></p>
          <dl className="mt-2 space-y-1.5">
            {FACTORS.map(([k, label]) => {
              const v = Number(idea.score_breakdown?.[k] ?? 0);
              return (
                <div key={k} className="text-xs">
                  <dt className="flex justify-between text-muted"><span>{label}</span><span className="tabular">{Math.round(v * 100)}</span></dt>
                  <dd className="mt-0.5 h-1.5 overflow-hidden rounded-full bg-sunken"><span className={`block h-full ${idea.channel_slug === "ai" ? "bg-pixel" : "bg-penny"}`} style={{ width: `${v * 100}%` }} /></dd>
                </div>
              );
            })}
          </dl>
        </div>
      </div>
    </article>
  );
}
