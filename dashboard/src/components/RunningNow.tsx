import { LoaderCircle } from "lucide-react";
import { Link } from "react-router-dom";
import { jobTitle, useRunningJobs } from "../lib/activity";

/** Always-visible "is the studio working?" line in the menu. */
export default function RunningNow() {
  const q = useRunningJobs();
  const jobs = q.data ?? [];
  const running = jobs.filter((j) => j.status === "running");
  const first = running[0] ?? jobs[0];
  // "idle" only when the database confirmed nothing is running or waiting
  const text = !q.isSuccess ? (q.isError ? "Couldn't check what's running" : "Checking what's running…")
    : !first ? "Studio idle" : running.length
    ? `${first.progress?.label ?? jobTitle(first)}${running.length > 1 ? ` (+${running.length - 1} more)` : ""}`
    : `${jobs.length} job${jobs.length === 1 ? "" : "s"} waiting to start`;
  return (
    <Link to="/activity" aria-live="polite" title={text}
      className={`flex items-center gap-2 rounded-lg px-3 py-2 text-xs font-medium ${running.length ? "bg-pixel-soft text-pixel" : q.isError ? "bg-alert-soft text-alert" : "bg-sunken text-muted"}`}>
      <LoaderCircle size={14} className={running.length ? "animate-spin" : ""} aria-hidden />
      <span className="truncate">{running.length ? "Working: " : ""}{text}</span>
    </Link>
  );
}
