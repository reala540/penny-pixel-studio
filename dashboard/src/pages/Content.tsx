import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronRight, Lightbulb, PlusCircle } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import ClearButton from "../components/ClearButton";
import { Confirm, Empty, ErrorNote, HostTag, Loading, NotConfirmed, PageHeader, StatusBadge, useToast } from "../components/ui";
import { approveProject, must } from "../lib/api";
import { isCleared, useCleared } from "../lib/clear";
import { CONTENT_TABS, tabStatuses } from "../lib/content";
import { fmtDuration } from "../lib/format";
import { useUrlState } from "../lib/state";
import { projectPath } from "../lib/routes";
import { supabase } from "../lib/supabase";
import type { Project } from "../lib/types";
import { Detail } from "./Review";

export default function Content() {
  const [params, setParams] = useSearchParams();
  const qc = useQueryClient();
  const toast = useToast();
  const tab = params.get("tab") ?? "needs-you";
  // filters and the page are kept in the address: coming back (or refreshing) shows the same list
  const [q, setQ] = useUrlState<string>("q", "");
  const [channel, setChannel] = useUrlState<string>("channel", "all");
  const [format, setFormat] = useUrlState<string>("format", "all");
  const [pageText, setPageText] = useUrlState<string>("page", "0");
  const page = Math.max(0, Number(pageText) || 0);
  const setPage = (n: number | ((p: number) => number)) => setPageText(String(typeof n === "function" ? n(page) : n));
  const [askAll, setAskAll] = useState(false);
  const cleared = useCleared();
  const statuses = tabStatuses(tab);
  const data = useQuery({
    queryKey: ["content", tab, q, channel, format, page],
    queryFn: async () => {
      let query = supabase.from("content_projects").select("*").order("created_at", { ascending: false }).range(page * 50, page * 50 + 49);
      if (statuses) query = query.in("status", [...statuses]);
      if (q.trim()) query = query.ilike("title", `%${q.trim()}%`);
      if (channel !== "all") query = query.eq("channel_slug", channel);
      if (format !== "all") query = query.eq("format", format);
      else if (tab === "needs-you" || tab === "in-progress") query = query.is("parent_project_id", null);
      return (await must(query)) as Project[];
    },
  });
  const counts = useQuery({
    queryKey: ["content-counts"],
    queryFn: async () => {
      const out: Record<string, number> = {};
      for (const [key, , statuses] of CONTENT_TABS) {
        let query=supabase.from("content_projects").select("id",{count:"exact",head:true}).is("parent_project_id",null);
        if(statuses)query=query.in("status",[...statuses]);
        const {count,error}=await query;
        if(error)throw new Error(error.message);
        out[key]=count??0;
      }
      return out;
    },
  });
  const published = useQuery({
    queryKey: ["library-published"],
    enabled: tab === "published" || tab === "all",
    queryFn: async () => (await must(supabase.from("published_posts").select("url, platform, method, published_at, scheduled_posts(content_variants(project_id))").order("published_at", { ascending: false }).limit(500))) as any[],
  });
  const links = new Map<string, any[]>();
  for (const p of published.data ?? []) {
    const pid = p.scheduled_posts?.content_variants?.project_id;
    if (pid) links.set(pid, [...(links.get(pid) ?? []), p]);
  }
  // "Clear drafts" hides rejected and failed packages made so far (as in the old Library)
  const rows = (data.data ?? []).filter((p) => !(["rejected", "failed"].includes(p.status) && isCleared(cleared.map, "library", p.created_at)));
  const eligible = tab === "needs-you" ? rows.filter((p) => p.status === "ready_for_review" && !p.parent_project_id && !(p.quality_report?.issues ?? []).length) : [];
  const [bulkResults, setBulkResults] = useState<{ title: string; ok: boolean; error?: string }[]>([]);
  const approveAll = useMutation({
    mutationFn: async () => {
      const outcomes: { title: string; ok: boolean; error?: string }[] = [];
      for (const p of eligible) {
        try { await approveProject(p.id, p.current_script_version_id, "approved in bulk"); outcomes.push({ title: p.title, ok: true }); }
        catch (e) { outcomes.push({ title: p.title, ok: false, error: (e as Error).message }); }
      }
      return outcomes;
    },
    onSuccess: (outcomes) => {
      setBulkResults(outcomes);
      const approved = outcomes.filter((x) => x.ok).length;
      toast(`${approved} approved; ${outcomes.length - approved} could not be approved.`, approved === outcomes.length ? "good" : "bad");
    },
    onSettled: () => { qc.invalidateQueries(); },
  });
  const filtersOn = q.trim() !== "" || channel !== "all" || format !== "all";
  const setTab = (t: string) => { const p = new URLSearchParams(params); p.set("tab", t); p.delete("page"); setParams(p); };

  return (
    <>
      <PageHeader title="Content" intro="Every package the studio has made: what needs you, what's being made, what's scheduled and what's out."
        actions={tab === "needs-you" && eligible.length > 0
          ? <button className="btn-primary" onClick={() => setAskAll(true)} disabled={approveAll.isPending}>Approve all {eligible.length} that passed every check</button>
          : <Link to="/create" className="btn-primary"><PlusCircle size={15} aria-hidden />Create content</Link>} />
      <Confirm open={askAll} title={`Approve ${eligible.length} packages?`} confirmLabel={`Approve ${eligible.length}`}
        body="Only packages that passed every check are approved. Anything that needs a look stays for you."
        onCancel={() => setAskAll(false)} onConfirm={() => { setAskAll(false); approveAll.mutate(); }} />
      {bulkResults.length > 0 && <ul aria-label="Approval results" className="mb-4 rounded-xl border border-line p-3 text-sm">{bulkResults.map((x, i) => <li key={i}>{x.title}: {x.ok ? "Approved" : `Not approved — ${x.error}`}</li>)}</ul>}
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div role="tablist" aria-label="Show" className="flex flex-wrap gap-1">
          {CONTENT_TABS.map(([k, label]) => (
            <button key={k} role="tab" aria-selected={tab === k} onClick={() => setTab(k)}
              className={`rounded-lg px-3 py-1.5 text-sm ${tab === k ? "bg-ink text-surface" : "text-muted hover:bg-sunken hover:text-ink"}`}>
              {label}{counts.data?.[k] ? <span className="ml-1 tabular opacity-70">{counts.data[k]}</span> : null}
            </button>
          ))}
        </div>
        <Link to="/content/ideas" className="btn-quiet"><Lightbulb size={14} aria-hidden />Ideas</Link>
      </div>
      <form role="search" className="mb-4 grid gap-2 sm:grid-cols-[1fr_auto_auto_auto]" onSubmit={(e) => e.preventDefault()}>
        <label className="sr-only" htmlFor="content-q">Search titles</label>
        <input id="content-q" className="field" placeholder="Search titles" value={q} onChange={(e) => setQ(e.target.value)} />
        <select aria-label="Channel" className="field" value={channel} onChange={(e) => setChannel(e.target.value)}>
          <option value="all">Both channels</option><option value="ai">Pixel · AI</option><option value="money">Penny · Money</option>
        </select>
        <select aria-label="Type" className="field" value={format} onChange={(e) => setFormat(e.target.value)}>
          <option value="all">Videos and Shorts</option><option value="long">Videos</option><option value="short">Shorts</option>
        </select>
        {filtersOn ? <button type="button" className="btn-quiet" onClick={() => { setQ(""); setChannel("all"); setFormat("all"); }}>Clear filters</button> : <span />}
      </form>
      <nav aria-label="Content pages" className="mb-3 flex items-center gap-3"><button className="btn-quiet" disabled={!page || data.isFetching} onClick={() => setPage((n)=>n-1)}>Previous</button><span className="text-sm">Page {page+1}</span><button className="btn-quiet" disabled={(data.data?.length??0)<50 || data.isFetching} onClick={() => setPage((n)=>n+1)}>Next</button></nav>
      {tab === "not-used" && (
        <div className="mb-3"><ClearButton label="Clear drafts" title="Clear rejected and failed items?" done="Rejected and failed items cleared"
          body="Rejected and failed packages made so far are hidden from this list. Nothing is deleted. You can undo this." onClear={() => cleared.clear("library")} /></div>
      )}
      {data.isLoading ? <Loading /> : data.isError ? <NotConfirmed q={data} what="your content" /> : rows.length === 0 ? (
        tab === "needs-you"
          ? <Empty title="You're all caught up">New packages arrive after Sunday's production, or <Link to="/create" className="text-pixel underline">create content</Link>.</Empty>
          : <Empty title="Nothing here">Try another tab, search or filter.</Empty>
      ) : (
        <ul className="divide-y divide-line rounded-xl border border-line bg-surface">
          {rows.map((p) => (
            <li key={p.id}>
              <Link to={projectPath(p.id)} className="flex flex-wrap items-center gap-3 px-4 py-3 hover:bg-sunken">
                <span className="min-w-0 flex-1">
                  <span className="flex flex-wrap items-center gap-2"><HostTag channel={p.channel_slug} /><span className="text-xs text-muted">{p.format === "long" ? "Video" : "Short"}{p.recipe?.preview_seconds ? ` · ${fmtDuration(p.recipe.preview_seconds)}` : ""} · made {new Date(p.created_at).toLocaleDateString("en-GB")}</span></span>
                  <span className="mt-0.5 block font-medium leading-snug">{p.title}</span>
                  {p.status === "needs_attention" && (p.quality_report?.issues ?? []).length > 0 && <span className="block text-xs text-alert">{(p.quality_report.issues as string[]).length} thing(s) to look at: {(p.quality_report.issues as string[])[0]}</span>}
                  {(links.get(p.id) ?? []).length > 0 && <span className="block text-xs text-muted">Posted on {(links.get(p.id) ?? []).map((l) => l.platform).join(", ")}</span>}
                </span>
                <StatusBadge status={p.status} />
                <ChevronRight size={16} className="text-muted" aria-hidden />
              </Link>
            </li>
          ))}
        </ul>
      )}
    </>
  );
}

/** /content/:projectId — one page per package. */
export function ProjectPage() {
  const { projectId } = useParams();
  const title = useQuery({
    queryKey: ["project-crumb", projectId],
    queryFn: async () => ((await must(supabase.from("content_projects").select("title, status, parent_project_id").eq("id", projectId!))) as any[])[0] ?? null,
  });
  const crumbTab = title.data && ["ready_for_review", "needs_attention"].includes(title.data.status) ? ["needs-you", "Needs you"]
    : title.data && ["published"].includes(title.data.status) ? ["published", "Published"] : ["all", "All"];
  return (
    <>
      <nav aria-label="Breadcrumb" className="mb-3 text-sm text-muted">
        <Link to="/content" className="hover:underline">Content</Link> › <Link to={`/content?tab=${crumbTab[0]}`} className="hover:underline">{crumbTab[1]}</Link>
        {title.data?.title && <> › <span className="text-ink">{title.data.title}</span></>}
      </nav>
      {title.data === null && !title.isLoading ? <Empty title="This package doesn't exist">It may have been removed. <Link to="/content" className="text-pixel underline">Back to Content</Link></Empty>
        : title.data?.parent_project_id ? <p className="mb-3 text-sm">This is a Short. <Link to={projectPath(title.data.parent_project_id)} className="text-pixel underline">Open its package</Link></p> : null}
      {projectId && title.data !== null && <Detail key={projectId} id={projectId} />}
    </>
  );
}
