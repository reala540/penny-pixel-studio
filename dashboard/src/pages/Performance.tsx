import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { Empty, Loading, NotConfirmed, PageHeader } from "../components/ui";
import { missingFunction, must, useTimezone } from "../lib/api";
import { fmtDateTime } from "../lib/format";
import { boostIdeas, emptyReason, fmtCount, fmtMinutes, fmtPercent, fmtSeconds, groupBy, KIND_LABEL, type PostRow, weekdayHour } from "../lib/performance";
import { supabase } from "../lib/supabase";

const NEEDS_UPDATE = "needs_update" as const;

async function rpc<T>(name: string, args: Record<string, unknown>): Promise<T | typeof NEEDS_UPDATE> {
  const res = await supabase.rpc(name, args);
  if (missingFunction(res.error)) return NEEDS_UPDATE;
  if (res.error) throw new Error(res.error.message);
  return res.data as T;
}

function Cell({ value, row, column }: { value: string | null; row: PostRow; column: string }) {
  if (value != null) return <span className="tabular">{value}</span>;
  const why = emptyReason(row, column);
  return <span className="text-muted" title={why} aria-label={why}>—</span>;
}

function Stat({ label, value, note }: { label: string; value: string | null; note?: string }) {
  return (
    <div className="rounded-xl border border-line bg-surface p-4">
      <p className="text-xs font-medium uppercase tracking-wide text-muted">{label}</p>
      <p className="mt-1 font-display text-2xl font-bold tabular">{value ?? <span className="text-base font-medium text-muted">Not available yet</span>}</p>
      {note && <p className="mt-1 text-xs text-muted">{note}</p>}
    </div>
  );
}

export default function Performance() {
  const tz = useTimezone();
  const posts = useQuery({ queryKey: ["performance", "posts"], queryFn: () => rpc<PostRow[]>("studio_performance", { p_days: 90 }) });
  const accounts = useQuery({
    queryKey: ["performance", "accounts"],
    queryFn: async () => {
      const rows = await supabase.from("account_metrics").select("social_account_id, collected_on, views, watch_minutes, subscribers_gained, top_countries, missing, note, social_accounts(label)")
        .order("collected_on", { ascending: false }).limit(50);
      if (rows.error?.code === "42P01" || rows.error?.code === "PGRST205") return NEEDS_UPDATE;
      return must(Promise.resolve(rows)) as Promise<any[]>;
    },
  });
  const costs = useQuery({ queryKey: ["performance", "costs"], queryFn: () => rpc<any[]>("studio_package_costs", { p_days: 90 }) });

  if (posts.isLoading) return <Loading label="Loading performance" />;
  if (posts.isError) return <NotConfirmed q={posts} what="performance numbers" />;
  if (posts.data === NEEDS_UPDATE) {
    return (
      <>
        <PageHeader title="Performance" />
        <p role="status" className="rounded-xl bg-sunken p-4 text-sm">This page needs the latest database update. Run GitHub → Actions → First-time setup (keys only), then come back.</p>
      </>
    );
  }
  const rows = posts.data ?? [];
  const withData = rows.filter((r) => r.views != null);
  const latest = new Map<string, any>();
  for (const a of accounts.data === NEEDS_UPDATE ? [] : accounts.data ?? []) if (!latest.has(a.social_account_id)) latest.set(a.social_account_id, a);
  const channels = [...latest.values()];
  const sum = (f: (a: any) => number | null) => (channels.some((a) => f(a) != null) ? channels.reduce((t, a) => t + Number(f(a) ?? 0), 0) : null);
  const countries = new Map<string, number>();
  for (const a of channels) for (const c of a.top_countries ?? []) countries.set(c.country, (countries.get(c.country) ?? 0) + Number(c.views));
  const topCountries = [...countries.entries()].sort((a, b) => b[1] - a[1]).slice(0, 8);
  const lastCollected = channels[0]?.collected_on;
  const boosts = boostIdeas(rows);

  return (
    <>
      <PageHeader title="Performance" intro="Read-only numbers from your platforms, checked once a day. Looking here never posts, approves or spends anything." />

      <section aria-labelledby="sources" className="mb-6">
        <h2 id="sources" className="section-title mb-2">Where the numbers come from</h2>
        <ul className="grid gap-2 text-sm sm:grid-cols-2 lg:grid-cols-4">
          <li className="rounded-lg border border-line bg-surface p-3"><b>YouTube</b>: {lastCollected ? <>last checked {lastCollected}. YouTube's numbers arrive 1–3 days late.</> : "not collected yet: the next daily check reads it."}</li>
          <li className="rounded-lg border border-line bg-surface p-3"><b>Facebook</b>: not collected yet. It needs the Page insights permission on your Facebook app.</li>
          <li className="rounded-lg border border-line bg-surface p-3"><b>X</b>: not read. X charges for reading post stats, so check them in the X app.</li>
          <li className="rounded-lg border border-line bg-surface p-3"><b>TikTok, Instagram</b>: not connected yet.</li>
        </ul>
      </section>

      <section aria-labelledby="last28" className="mb-6">
        <h2 id="last28" className="section-title mb-2">YouTube, last 28 days</h2>
        <div className="grid gap-3 sm:grid-cols-3">
          <Stat label="Views" value={fmtCount(sum((a) => a.views))} />
          <Stat label="Watch time" value={fmtMinutes(sum((a) => a.watch_minutes))} />
          <Stat label="Subscribers gained" value={fmtCount(sum((a) => a.subscribers_gained))} />
        </div>
        {topCountries.length > 0 && (
          <div className="mt-3 rounded-xl border border-line bg-surface p-4 text-sm">
            <p className="font-medium">Top countries</p>
            <ol className="mt-2 grid gap-1 sm:grid-cols-2 lg:grid-cols-4">
              {topCountries.map(([c, v], i) => <li key={c} className="tabular">{i + 1}. {c} · {fmtCount(v)} views</li>)}
            </ol>
          </div>
        )}
      </section>

      {boosts.length > 0 && (
        <section aria-labelledby="boost" className="mb-6 rounded-xl border border-penny/30 bg-penny-soft p-4 text-sm">
          <h2 id="boost" className="font-display text-base font-semibold">Worth boosting</h2>
          <p className="mt-1 text-muted">These are clearly beating your usual views on YouTube. If you want more reach, open the Facebook post and press Boost with a budget you choose. The studio never spends money.</p>
          <ul className="mt-2 space-y-1">
            {boosts.map((b) => <li key={b.project_id}>“{b.title}”: {fmtCount(b.views)} views (usual {fmtCount(b.usual)}){b.facebook.url && <> · <a className="underline" href={b.facebook.url} target="_blank" rel="noreferrer">open the Facebook post</a></>}</li>)}
          </ul>
        </section>
      )}

      {withData.length > 0 && (
        <section aria-labelledby="compare" className="mb-6">
          <h2 id="compare" className="section-title mb-2">What's working (average views per post with numbers)</h2>
          <div className="grid gap-3 md:grid-cols-3">
            {[
              { title: "Pixel (AI) vs Penny (Money)", groups: groupBy(withData, (r) => (r.channel_slug === "ai" ? "Pixel · AI" : "Penny · Money")) },
              { title: "By type", groups: groupBy(withData, (r) => KIND_LABEL[r.kind] ?? r.kind) },
              { title: "By posting day", groups: groupBy(withData, (r) => weekdayHour(r.published_at, tz).day) },
            ].map((b) => (
              <div key={b.title} className="rounded-xl border border-line bg-surface p-4 text-sm">
                <p className="font-medium">{b.title}</p>
                <ul className="mt-2 space-y-1">
                  {b.groups.map((g) => <li key={g.key} className="flex justify-between gap-2"><span>{g.key}</span><span className="tabular text-muted">{fmtCount(g.avgViews)} · {g.withData} post{g.withData === 1 ? "" : "s"}</span></li>)}
                </ul>
              </div>
            ))}
          </div>
          <p className="mt-2 text-xs text-muted">Small numbers of posts can mislead: treat early differences as hints, not results.</p>
        </section>
      )}

      <section aria-labelledby="posts" className="mb-6">
        <h2 id="posts" className="section-title mb-2">Posts in the last 90 days</h2>
        {rows.length === 0 ? <Empty title="Nothing published yet">Numbers appear here after your first posts go out.</Empty> : (
          <div className="overflow-x-auto rounded-xl border border-line bg-surface">
            <table className="w-full min-w-[860px] text-left text-sm">
              <thead className="border-b border-line text-xs uppercase tracking-wide text-muted">
                <tr>{["Post", "Account", "Published", "Views", "Watch time", "Avg view", "Click-through", "Likes", "Comments", "Shares"].map((h) => <th key={h} scope="col" className="px-3 py-2 font-medium">{h}</th>)}</tr>
              </thead>
              <tbody className="divide-y divide-line">
                {rows.map((r) => (
                  <tr key={r.published_post_id}>
                    <td className="max-w-[18rem] px-3 py-2"><Link to={`/content/${r.project_id}`} className="line-clamp-2 hover:underline">{r.title}</Link><span className="text-xs text-muted">{KIND_LABEL[r.kind] ?? r.kind}{r.url && <> · <a className="underline" href={r.url} target="_blank" rel="noreferrer">open</a></>}</span></td>
                    <td className="px-3 py-2">{r.account_label}</td>
                    <td className="whitespace-nowrap px-3 py-2 tabular text-muted">{fmtDateTime(r.published_at, tz)}</td>
                    <td className="px-3 py-2"><Cell value={fmtCount(r.views)} row={r} column="views" /></td>
                    <td className="px-3 py-2"><Cell value={fmtMinutes(r.watch_minutes)} row={r} column="watch_minutes" /></td>
                    <td className="px-3 py-2"><Cell value={fmtSeconds(r.avg_view_seconds)} row={r} column="avg_view_seconds" /></td>
                    <td className="px-3 py-2"><Cell value={fmtPercent(r.ctr)} row={r} column="ctr" /></td>
                    <td className="px-3 py-2"><Cell value={fmtCount(r.likes)} row={r} column="likes" /></td>
                    <td className="px-3 py-2"><Cell value={fmtCount(r.comments)} row={r} column="comments" /></td>
                    <td className="px-3 py-2"><Cell value={fmtCount(r.shares)} row={r} column="shares" /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <p className="mt-2 text-xs text-muted">"—" means the number isn't available: point at it to see why. Nothing is guessed.</p>
      </section>

      <section aria-labelledby="costs">
        <h2 id="costs" className="section-title mb-2">What each package cost to make</h2>
        {costs.isLoading ? <Loading /> : costs.isError ? <NotConfirmed q={costs} what="package costs" /> : costs.data === NEEDS_UPDATE ? null : (costs.data ?? []).length === 0 ? <p className="text-sm text-muted">No packages in the last 90 days.</p> : (
          <div className="overflow-x-auto rounded-xl border border-line bg-surface">
            <table className="w-full min-w-[640px] text-left text-sm">
              <thead className="border-b border-line text-xs uppercase tracking-wide text-muted">
                <tr>{["Package", "AI requests", "AI cost", "Render time", "X spend", "Total"].map((h) => <th key={h} scope="col" className="px-3 py-2 font-medium">{h}</th>)}</tr>
              </thead>
              <tbody className="divide-y divide-line">
                {(costs.data ?? []).map((c: any) => (
                  <tr key={c.project_id}>
                    <td className="max-w-[18rem] px-3 py-2"><Link to={`/content/${c.project_id}`} className="line-clamp-2 hover:underline">{c.title}</Link></td>
                    <td className="px-3 py-2 tabular">{fmtCount(c.ai_calls)}</td>
                    <td className="px-3 py-2 tabular">${Number(c.ai_cost_usd).toFixed(2)}</td>
                    <td className="px-3 py-2 tabular">{fmtMinutes(c.render_minutes)}</td>
                    <td className="px-3 py-2 tabular">${Number(c.x_spend_usd).toFixed(2)}</td>
                    <td className="px-3 py-2 font-medium tabular">${(Number(c.ai_cost_usd) + Number(c.x_spend_usd)).toFixed(2)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <p className="mt-2 text-xs text-muted">Most AI services you use are free, so their cost shows as $0. Render time uses GitHub's free minutes. Revenue appears once YouTube pays you.</p>
      </section>
    </>
  );
}
