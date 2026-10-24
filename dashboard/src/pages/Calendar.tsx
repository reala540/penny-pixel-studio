import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { DragEvent, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import ClearButton from "../components/ClearButton";
import { ErrorNote, HostMark, Loading, PageHeader, StatusBadge, useToast } from "../components/ui";
import { must, queueJob, useAccounts, useTimezone } from "../lib/api";
import { dayLabel, fmtDateTime, fmtTime, KIND_NAME, localDay, moveToDay, weekDays } from "../lib/format";
import { supabase } from "../lib/supabase";
import type { Post } from "../lib/types";
import { POST_SELECT, WeekPicker } from "./Home";

const MOVABLE = ["pending_approval", "scheduled"];

export default function Calendar() {
  const tz = useTimezone();
  const qc = useQueryClient();
  const toast = useToast();
  const [params, setParams] = useSearchParams();
  const [offset, setOffset] = useState(0);
  const [account, setAccount] = useState<string>("all");
  const [dragging, setDragging] = useState<string | null>(null);
  const days = weekDays(new Date(Date.now() + offset * 7 * 86_400_000), tz);
  const accounts = useAccounts();
  const posts = useQuery({
    queryKey: ["posts", days[0]],
    queryFn: async () => {
      const from = new Date(Date.parse(`${days[0]}T00:00:00Z`) - 86_400_000).toISOString();
      const to = new Date(Date.parse(`${days[6]}T23:59:59Z`) + 86_400_000).toISOString();
      return (await must(supabase.from("scheduled_posts").select(POST_SELECT).gte("scheduled_at", from).lte("scheduled_at", to).neq("status", "cancelled").order("scheduled_at"))) as unknown as Post[];
    },
  });
  const move = useMutation({
    mutationFn: async ({ id, when }: { id: string; when: string }) => must(supabase.from("scheduled_posts").update({ scheduled_at: when }).eq("id", id)),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["posts"] }); toast("Rescheduled"); },
    onError: (e) => toast((e as Error).message, "bad"),
  });

  const visible = (posts.data ?? []).filter((p) => account === "all" || p.social_account_id === account);
  const selected = (posts.data ?? []).find((p) => p.id === params.get("post"));
  const today = localDay(new Date(), tz);

  function onDrop(e: DragEvent, day: string) {
    e.preventDefault();
    const id = e.dataTransfer.getData("text/plain");
    const p = (posts.data ?? []).find((x) => x.id === id);
    setDragging(null);
    if (!p || localDay(p.scheduled_at, tz) === day) return;
    const when = moveToDay(p.scheduled_at, day, tz);
    const clash = (posts.data ?? []).some((x) => x.id !== p.id && x.social_account_id === p.social_account_id && Math.abs(Date.parse(x.scheduled_at) - Date.parse(when)) < 30 * 60_000);
    if (clash) return toast("Another post on that account is within 30 minutes of that time. Pick a different day or time.", "bad");
    move.mutate({ id, when });
  }

  return (
    <>
      <PageHeader title="Calendar" intro="Drag a post to another day, or open it to change the exact time. Dashed posts are waiting for your approval." />
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <WeekPicker offset={offset} setOffset={setOffset} />
        <label className="flex items-center gap-2 text-sm">
          <span className="text-muted">Account</span>
          <select className="field w-auto" value={account} onChange={(e) => setAccount(e.target.value)}>
            <option value="all">All accounts</option>
            {(accounts.data ?? []).map((a) => <option key={a.id} value={a.id}>{a.label}</option>)}
          </select>
        </label>
      </div>
      <ErrorNote error={posts.error} />
      {posts.isLoading ? <Loading /> : (
        <div className="grid grid-cols-1 gap-6 2xl:grid-cols-[1fr_320px]">
          <div className="grid min-w-0 grid-cols-1 gap-2 md:grid-cols-7">
            {days.map((d) => {
              const { weekday, date } = dayLabel(d);
              const list = visible.filter((p) => localDay(p.scheduled_at, tz) === d);
              return (
                <section key={d} aria-label={`${weekday} ${date}`} onDragOver={(e) => e.preventDefault()} onDrop={(e) => onDrop(e, d)}
                  className={`min-h-[8rem] rounded-xl border p-2 ${dragging ? "border-dashed border-pixel/50" : "border-line"} ${d === today ? "bg-surface" : "bg-surface/60"}`}>
                  <h2 className="mb-2 flex items-baseline justify-between px-1 text-xs">
                    <span className={`font-semibold ${d === today ? "text-ink" : "text-muted"}`}>{weekday}</span>
                    <span className="tabular text-muted">{date}</span>
                  </h2>
                  <ul className="space-y-1.5">
                    {list.map((p) => {
                      const ch = p.content_variants?.content_projects?.channel_slug ?? "ai";
                      const movable = MOVABLE.includes(p.status);
                      return (
                        <li key={p.id} draggable={movable} onDragStart={(e) => { e.dataTransfer.setData("text/plain", p.id); setDragging(p.id); }} onDragEnd={() => setDragging(null)}>
                          <button onClick={() => setParams({ post: p.id })}
                            className={`w-full rounded-lg border px-2 py-1.5 text-left text-xs ${ch === "ai" ? "bg-pixel-soft" : "bg-penny-soft"} ${p.status === "pending_approval" ? "border-dashed border-muted/60" : "border-transparent"} ${params.get("post") === p.id ? "ring-2 ring-ink" : ""} ${movable ? "cursor-grab" : ""}`}>
                            <span className="flex items-center gap-1 font-medium"><HostMark channel={ch} size={7} /><span className="tabular">{fmtTime(p.scheduled_at, tz)}</span></span>
                            <span className="block truncate text-muted">{p.social_accounts?.label}</span>
                            <span className="mt-0.5 line-clamp-2">{p.content_variants?.title || p.content_variants?.content_projects?.title}</span>
                            {p.status !== "pending_approval" && <span className="mt-1 block"><StatusBadge status={p.status} /></span>}
                          </button>
                        </li>
                      );
                    })}
                  </ul>
                </section>
              );
            })}
          </div>
          <aside aria-label="Selected post">
            {selected ? <PostPanel post={selected} tz={tz} onMove={(when) => move.mutate({ id: selected.id, when })} /> : (
              <p className="rounded-xl border border-dashed border-line p-5 text-sm text-muted">Choose a post to see its details, change its time or fix a problem.</p>
            )}
          </aside>
        </div>
      )}
    </>
  );
}

function toLocalInput(iso: string, tz: string): string {
  const d = new Date(iso);
  const parts = new Intl.DateTimeFormat("en-CA", { timeZone: tz, year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false }).formatToParts(d);
  const get = (t: string) => parts.find((p) => p.type === t)?.value ?? "00";
  return `${get("year")}-${get("month")}-${get("day")}T${get("hour") === "24" ? "00" : get("hour")}:${get("minute")}`;
}

function fromLocalInput(value: string, tz: string): string {
  // Find the UTC instant whose local time in `tz` equals `value`.
  const guess = Date.parse(`${value}:00Z`);
  const shown = Date.parse(`${toLocalInput(new Date(guess).toISOString(), tz)}:00Z`);
  return new Date(guess - (shown - guess)).toISOString();
}

function PostPanel({ post, tz, onMove }: { post: Post; tz: string; onMove: (when: string) => void }) {
  const qc = useQueryClient();
  const toast = useToast();
  const [when, setWhen] = useState(toLocalInput(post.scheduled_at, tz));
  const movable = MOVABLE.includes(post.status);
  const retry = useMutation({
    mutationFn: async () => must(supabase.from("scheduled_posts").update({ status: "scheduled" }).eq("id", post.id)),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["posts"] }); toast("Will try again at the next check"); },
    onError: (e) => toast((e as Error).message, "bad"),
  });
  const expired = post.status === "blocked" && (post.last_error ?? "").includes("expired");
  return (
    <div className="space-y-4 rounded-xl border border-line bg-surface p-5">
      <div>
        <p className="text-xs text-muted">{post.social_accounts?.label} · {KIND_NAME[post.content_variants?.kind ?? ""]}</p>
        <h2 className="mt-1 font-display text-lg font-semibold leading-snug">{post.content_variants?.title || post.content_variants?.content_projects?.title}</h2>
        <div className="mt-2"><StatusBadge status={post.status} /></div>
      </div>
      <p className="text-sm">{fmtDateTime(post.scheduled_at, tz)}</p>
      {post.last_error && <p className="rounded-lg bg-alert-soft px-3 py-2 text-sm text-alert">{post.last_error}</p>}
      {post.published_posts?.url && <a className="btn-quiet w-full" href={post.published_posts.url} target="_blank" rel="noreferrer">Open the post</a>}
      {movable && (
        <form className="space-y-2" onSubmit={(e) => { e.preventDefault(); onMove(fromLocalInput(when, tz)); }}>
          <label className="block text-sm font-medium" htmlFor="when">New time ({tz})</label>
          <input id="when" type="datetime-local" className="field" value={when} onChange={(e) => setWhen(e.target.value)} />
          <button className="btn-quiet w-full">Change time</button>
        </form>
      )}
      {expired && (
        <button className="btn-primary w-full" onClick={() => queueJob("recheck_project", { projectId: post.content_variants?.project_id }).then(() => toast("Fact re-check requested"))}>
          Re-check the facts
        </button>
      )}
      {["failed", "needs_review"].includes(post.status) && (
        <div className="space-y-2 text-sm">
          {post.status === "needs_review" && <p className="text-muted">Check the platform first: if the post is already there, don't retry. Use "Post it yourself" in Home to record it.</p>}
          <button className="btn-quiet w-full" onClick={() => retry.mutate()}>Try again</button>
        </div>
      )}
      {movable && (
        <ClearButton label="Cancel this post" className="btn-quiet w-full" danger title="Cancel this post?" done="Post cancelled, slot freed"
          body="This post won't go out and its time slot is freed. The video and the other posts in the package aren't affected. You can undo this for a few seconds."
          onClear={async () => {
            const before = post.status;
            await must(supabase.from("scheduled_posts").update({ status: "cancelled" }).eq("id", post.id));
            await supabase.from("audit_logs").insert({ actor: "owner", action: "post_cancelled", target_type: "scheduled_post", target_id: post.id, details: { was: before } });
            qc.invalidateQueries({ queryKey: ["posts"] });
            return async () => {
              await must(supabase.from("scheduled_posts").update({ status: before }).eq("id", post.id).eq("status", "cancelled"));
              qc.invalidateQueries({ queryKey: ["posts"] });
            };
          }} />
      )}
      <Link to={`/review/${post.content_variants?.project_id}`} className="block text-sm font-medium text-pixel underline-offset-2 hover:underline">Open the package</Link>
    </div>
  );
}
