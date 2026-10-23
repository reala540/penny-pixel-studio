import { AlertTriangle, Check, Clock } from "lucide-react";
import { Link } from "react-router-dom";
import { dayLabel, fmtTime, KIND_NAME, localDay, statusText } from "../lib/format";
import type { Account, Post } from "../lib/types";
import { HostMark } from "./ui";

const PROBLEM = ["failed", "blocked", "needs_review", "needs_manual"];

/** The week as a broadcast rundown: one row per account, one column per day. */
export default function Rundown({ accounts, posts, days, tz, today }: {
  accounts: Account[]; posts: Post[]; days: string[]; tz: string; today: string;
}) {
  const byCell = new Map<string, Post[]>();
  for (const p of posts) {
    const k = `${p.social_account_id}|${localDay(p.scheduled_at, tz)}`;
    byCell.set(k, [...(byCell.get(k) ?? []), p]);
  }
  return (
    <div className="overflow-x-auto rounded-xl border border-line bg-surface">
      <table className="w-full min-w-[860px] table-fixed border-collapse text-left">
        <caption className="sr-only">Posts planned for each account this week</caption>
        <colgroup>
          <col className="w-36" />
          {days.map((d) => <col key={d} />)}
        </colgroup>
        <thead>
          <tr className="border-b border-line">
            <th scope="col" className="px-3 py-2.5 text-xs font-medium text-muted">Account</th>
            {days.map((d) => {
              const { weekday, date } = dayLabel(d);
              const isToday = d === today;
              return (
                <th key={d} scope="col" className={`px-2 py-2.5 text-xs font-medium ${isToday ? "text-ink" : "text-muted"}`}>
                  <span className={isToday ? "rounded-md bg-ink px-1.5 py-0.5 text-surface" : ""}>{weekday}</span>{" "}
                  <span className="tabular">{date}</span>
                </th>
              );
            })}
          </tr>
        </thead>
        <tbody>
          {accounts.map((a) => (
            <tr key={a.id} className="border-b border-line last:border-0">
              <th scope="row" className="px-3 py-2 align-top text-sm font-medium">
                {a.label}
                {a.oauth_connections?.status !== "connected" && (
                  <Link to="/settings" className="mt-0.5 block text-xs font-normal text-alert underline-offset-2 hover:underline">Not connected</Link>
                )}
              </th>
              {days.map((d) => {
                const cell = (byCell.get(`${a.id}|${d}`) ?? []).sort((x, y) => x.scheduled_at.localeCompare(y.scheduled_at));
                return (
                  <td key={d} className={`px-1.5 py-1.5 align-top ${d === today ? "bg-sunken/60" : ""}`}>
                    <div className="flex flex-col gap-1">
                      {cell.map((p) => <Chip key={p.id} post={p} tz={tz} />)}
                    </div>
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Chip({ post, tz }: { post: Post; tz: string }) {
  const channel = post.content_variants?.content_projects?.channel_slug ?? "ai";
  const waiting = post.status === "pending_approval";
  const problem = PROBLEM.includes(post.status);
  const done = post.status === "published";
  const bg = channel === "ai" ? "bg-pixel-soft" : "bg-penny-soft";
  const title = post.content_variants?.title || post.content_variants?.content_projects?.title || "";
  return (
    <Link
      to={`/calendar?post=${post.id}`}
      title={`${title} — ${statusText(post.status)}`}
      className={`group block rounded-md border px-1.5 py-1 text-[11px] leading-tight ${bg} ${waiting ? "border-dashed border-muted/60" : problem ? "border-alert" : "border-transparent"} ${done ? "opacity-70" : ""}`}
    >
      <span className="flex items-center gap-1 font-medium">
        <HostMark channel={channel} size={7} />
        <span className="tabular">{fmtTime(post.scheduled_at, tz)}</span>
        <span className="text-muted">{KIND_NAME[post.content_variants?.kind ?? ""] ?? ""}</span>
        <span className="ml-auto">
          {done && <Check size={11} aria-label="Published" />}
          {problem && <AlertTriangle size={11} className="text-alert" aria-label={statusText(post.status)} />}
          {waiting && <Clock size={11} className="text-muted" aria-label="Waiting for approval" />}
        </span>
      </span>
      <span className="mt-0.5 line-clamp-2 text-ink/80">{title}</span>
    </Link>
  );
}
