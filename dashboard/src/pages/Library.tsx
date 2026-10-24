import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";
import ClearButton from "../components/ClearButton";
import { Empty, ErrorNote, HostTag, Loading, PageHeader, StatusBadge } from "../components/ui";
import { must } from "../lib/api";
import { isCleared, useCleared } from "../lib/clear";
import { fmtDuration } from "../lib/format";
import { supabase } from "../lib/supabase";
import type { Project } from "../lib/types";

export default function LibraryPage() {
  const [q, setQ] = useState("");
  const [channel, setChannel] = useState("all");
  const [format, setFormat] = useState("all");
  const [status, setStatus] = useState("all");
  const data = useQuery({
    queryKey: ["library", q, channel, format, status],
    queryFn: async () => {
      let query = supabase.from("content_projects").select("*").order("created_at", { ascending: false }).limit(100);
      if (q.trim()) query = query.ilike("title", `%${q.trim()}%`);
      if (channel !== "all") query = query.eq("channel_slug", channel);
      if (format !== "all") query = query.eq("format", format);
      if (status !== "all") query = query.eq("status", status);
      return (await must(query)) as Project[];
    },
  });
  const published = useQuery({
    queryKey: ["library-published"],
    queryFn: async () => (await must(supabase.from("published_posts").select("url, platform, method, published_at, scheduled_posts(content_variants(project_id))").order("published_at", { ascending: false }).limit(500))) as any[],
  });
  const cleared = useCleared();
  const filtersOn = q.trim() !== "" || channel !== "all" || format !== "all" || status !== "all";
  // "Clear drafts" hides rejected and failed items made so far; everything else always shows.
  const rows = (data.data ?? []).filter((p) => !(["rejected", "failed"].includes(p.status) && isCleared(cleared.map, "library", p.created_at)));
  const links = new Map<string, any[]>();
  for (const p of published.data ?? []) {
    const pid = p.scheduled_posts?.content_variants?.project_id;
    if (pid) links.set(pid, [...(links.get(pid) ?? []), p]);
  }

  return (
    <>
      <PageHeader title="Library" intro="Everything the studio has made, with the scripts, sources and where each piece was posted."
        actions={<ClearButton label="Clear drafts" title="Clear rejected and failed items?" done="Rejected and failed items cleared"
          body="Rejected and failed videos made so far are hidden from the Library. Published and approved work always stays, and nothing is deleted. You can undo this."
          onClear={() => cleared.clear("library")} />} />
      <form role="search" className="mb-6 grid gap-2 sm:grid-cols-[1fr_auto_auto_auto]" onSubmit={(e) => e.preventDefault()}>
        <label className="sr-only" htmlFor="lib-q">Search titles</label>
        <input id="lib-q" className="field" placeholder="Search titles" value={q} onChange={(e) => setQ(e.target.value)} />
        <select aria-label="Channel" className="field" value={channel} onChange={(e) => setChannel(e.target.value)}>
          <option value="all">Both channels</option><option value="ai">Pixel · AI</option><option value="money">Penny · Money</option>
        </select>
        <select aria-label="Format" className="field" value={format} onChange={(e) => setFormat(e.target.value)}>
          <option value="all">Videos and Shorts</option><option value="long">Videos</option><option value="short">Shorts</option>
        </select>
        <select aria-label="Status" className="field" value={status} onChange={(e) => setStatus(e.target.value)}>
          <option value="all">Any status</option>
          {["ready_for_review", "needs_attention", "approved", "published", "rejected", "failed"].map((s) => <option key={s} value={s}>{s.replace(/_/g, " ")}</option>)}
        </select>
        {filtersOn && <button type="button" className="btn-quiet sm:col-span-4 sm:justify-self-start" onClick={() => { setQ(""); setChannel("all"); setFormat("all"); setStatus("all"); }}>Clear filters</button>}
      </form>
      <ErrorNote error={data.error} />
      {data.isLoading ? <Loading /> : rows.length === 0 ? <Empty title="Nothing found">Try a different search or filter.</Empty> : (
        <div className="overflow-x-auto rounded-xl border border-line bg-surface">
          <table className="w-full min-w-[640px] text-left text-sm">
            <thead className="border-b border-line text-xs text-muted">
              <tr><th className="px-4 py-2.5 font-medium">Title</th><th className="px-3 py-2.5 font-medium">Host</th><th className="px-3 py-2.5 font-medium">Type</th><th className="px-3 py-2.5 font-medium">Status</th><th className="px-3 py-2.5 font-medium">Posted on</th></tr>
            </thead>
            <tbody className="divide-y divide-line">
              {rows.map((p) => (
                <tr key={p.id} className="hover:bg-sunken/50">
                  <td className="px-4 py-2.5"><Link to={`/review/${p.id}`} className="font-medium hover:underline">{p.title}</Link>
                    <span className="block text-xs text-muted">{new Date(p.created_at).toLocaleDateString("en-GB")}</span></td>
                  <td className="px-3 py-2.5"><HostTag channel={p.channel_slug} /></td>
                  <td className="px-3 py-2.5 text-muted">{p.format === "long" ? "Video" : "Short"} {fmtDuration(p.recipe?.preview_seconds)}</td>
                  <td className="px-3 py-2.5"><StatusBadge status={p.status} /></td>
                  <td className="px-3 py-2.5">
                    <span className="flex flex-wrap gap-2">
                      {(links.get(p.id) ?? []).map((l, i) => l.url ? <a key={i} href={l.url} target="_blank" rel="noreferrer" className="text-pixel underline-offset-2 hover:underline">{l.platform}</a> : <span key={i} className="text-muted">{l.platform}</span>)}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}
