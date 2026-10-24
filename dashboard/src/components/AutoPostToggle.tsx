import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Bot, UserCheck } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";
import { must, useSaveSetting, useSetting } from "../lib/api";
import { useCleared, visibleAfterClear } from "../lib/clear";
import { callWorker, supabase, workerUrl } from "../lib/supabase";
import { Confirm, useToast } from "./ui";

/** Current mode, kept in sync with Telegram changes (polled, and refreshed when the tab regains focus). */
export function useAutoPost() {
  return useQuery({
    queryKey: ["setting", "auto_review_post"],
    refetchInterval: 10_000,
    refetchOnWindowFocus: true,
    queryFn: async () => {
      const rows = (await must(supabase.from("settings").select("value").eq("key", "auto_review_post"))) as { value: unknown }[];
      return rows[0]?.value === true;   // missing or anything else = OFF (the safe default)
    },
  });
}

async function setMode(on: boolean): Promise<{ on: boolean; reverted_posts: number; notified?: boolean }> {
  if (workerUrl) return callWorker("/api/autopost", { on, confirm: on });   // also tells Telegram and reviews what's waiting
  const { data, error } = await supabase.rpc("set_auto_review_post", { p_on: on, p_actor: "owner" });
  if (error) throw new Error(error.message);
  return data as { on: boolean; reverted_posts: number };
}

/** The always-visible "who approves" line: you, or Auto Review & Post. */
export function AutoPostBadge() {
  const on = useAutoPost().data === true;
  return (
    <Link to="/settings/automation" className={`flex items-center gap-2 rounded-lg px-3 py-2 text-xs font-medium ${on ? "bg-penny-soft text-penny" : "bg-sunken text-muted"}`}
      aria-label={`Approval: ${on ? "automatic. Auto Review and Post: ON" : "you approve each package. Auto Review and Post: OFF"}. Change in Settings.`}>
      {on ? <Bot size={14} aria-hidden /> : <UserCheck size={14} aria-hidden />}
      Approval: {on ? "Auto Review & Post" : "You approve"}
    </Link>
  );
}

/** What happens after a package is made, in the current mode (shown before Create package and on each project). */
export function ApprovalModeNotice({ compact = false }: { compact?: boolean }) {
  const q = useAutoPost();
  const on = q.data === true;
  if (q.isLoading) return <p className="text-sm text-muted">Checking who approves…</p>;
  return (
    <div role="note" className={`rounded-lg border px-3 py-2 text-sm ${on ? "border-penny/40 bg-penny-soft text-ink" : "border-line bg-sunken text-ink"}`}>
      {on ? (
        <><strong>Approval: Auto Review &amp; Post is ON.</strong>{compact ? " " : <br />}If every check passes and the independent AI review is confident,
          it's approved automatically and posts at its scheduled times. Anything else waits for you.</>
      ) : (
        <><strong>Approval: you approve.</strong>{compact ? " " : <br />}Nothing is posted until you approve it in Content.</>
      )}
      {" "}<Link to="/settings/automation" className="text-pixel underline-offset-2 hover:underline">Change</Link>
    </div>
  );
}

export default function AutoPostToggle({ compact = false }: { compact?: boolean }) {
  const qc = useQueryClient();
  const toast = useToast();
  const mode = useAutoPost();
  const on = mode.data === true;
  const [confirm, setConfirm] = useState(false);
  const change = useMutation({
    mutationFn: setMode,
    onSuccess: (r) => {
      qc.setQueryData(["setting", "auto_review_post"], r.on);
      qc.invalidateQueries({ queryKey: ["setting", "auto_review_post"] });
      qc.invalidateQueries({ queryKey: ["auto-reviews"] });
      const tg = r.notified === false ? " (Telegram couldn't be told)" : "";
      toast((r.on ? "Auto Review & Post is ON" : `Auto Review & Post is OFF${r.reverted_posts ? ` · ${r.reverted_posts} post(s) back in Review` : ""}`) + tg);
    },
    onError: (e) => toast((e as Error).message, "bad"),
  });
  return (
    <div className={compact ? "flex items-center gap-3" : "flex flex-wrap items-center gap-3"}>
      <button type="button" role="switch" aria-checked={on} disabled={mode.isLoading || change.isPending}
        onClick={() => (on ? change.mutate(false) : setConfirm(true))}
        className={`relative inline-flex h-7 w-12 shrink-0 items-center rounded-full border transition-colors ${on ? "border-penny bg-penny" : "border-line bg-sunken"} disabled:opacity-50`}>
        <span className={`inline-block h-5 w-5 rounded-full bg-surface shadow transition-transform ${on ? "translate-x-6" : "translate-x-1"}`} />
        <span className="sr-only">Auto Review and Post</span>
      </button>
      <span className="text-sm font-semibold text-ink" aria-live="polite">Auto Review &amp; Post: {mode.isLoading ? "…" : on ? "ON" : "OFF"}</span>
      {!compact && <span className="text-sm text-muted">{on ? "Packages that pass every check are approved and posted on schedule; the rest come to you." : "Every package waits for your approval."}</span>}
      <Confirm open={confirm} title="Turn on Auto Review & Post?" confirmLabel="Turn on"
        body={<>
          <p>The AI will approve a package only if it passed every quality, fact, freshness, destination and licence check
            and an independent AI reviewer is confident it's publishable. It then posts at its scheduled times, to your
            configured accounts only. When a check fails, the studio fixes that part and checks again (up to the number of
            attempts you set). Anything still failing, and any error, waits for you and is sent to Telegram.</p>
          <p className="mt-2">You can switch it off any time here or with /autopost off in Telegram; posts that haven't
            gone out yet go back to Review.</p>
          {!workerUrl && <p className="mt-2 text-alert">The Worker isn't connected, so Telegram won't be told about this change.</p>}
        </>}
        onConfirm={() => { setConfirm(false); change.mutate(true); }} onCancel={() => setConfirm(false)} />
    </div>
  );
}

/** How many times Auto Review & Post may fix a failed package and try again before it comes to you. */
export function AutoFixAttempts() {
  const cfg = useSetting<{ max_attempts?: number }>("auto_review_fix", {});
  const save = useSaveSetting();
  const toast = useToast();
  const value = Math.min(5, Math.max(0, Number(cfg.data?.max_attempts ?? 3)));
  return (
    <label className="mt-4 flex max-w-xl flex-wrap items-center gap-2 text-sm">
      <span className="text-ink">When a check fails, fix it and try again</span>
      <select aria-label="Automatic fix attempts" className="field w-auto" value={value} disabled={cfg.isLoading}
        onChange={(e) => save.mutate({ key: "auto_review_fix", value: { ...(cfg.data ?? {}), max_attempts: Number(e.target.value) } },
          { onSuccess: () => toast("Saved"), onError: (er) => toast((er as Error).message, "bad") })}>
        {[0, 1, 2, 3, 4, 5].map((n) => <option key={n} value={n}>{n === 0 ? "never (send to me)" : `up to ${n} time${n === 1 ? "" : "s"}`}</option>)}
      </select>
      <span className="basis-full text-xs text-muted">Only the part that failed is fixed (post text, script, facts or photos), then every check runs again. A wrong account or a policy concern is never retried.</span>
    </label>
  );
}

type AutoReview = { id: string; project_id: string; verdict: string; reasons: string[]; reviewer: string | null; attempt?: number; fix?: string | null;
  confidence: number | null; posts_scheduled: number; created_at: string; content_projects?: { title: string } | { title: string }[] | null };

export function AutoReviewLog() {
  const rows = useQuery({
    queryKey: ["auto-reviews"],
    refetchInterval: 30_000,
    queryFn: async () => (await must(supabase.from("auto_reviews").select("id,project_id,verdict,reasons,reviewer,confidence,posts_scheduled,created_at,attempt,fix,content_projects(title)")
      .order("created_at", { ascending: false }).limit(12))) as unknown as AutoReview[],
  });
  const cleared = useCleared();
  const list = visibleAfterClear(rows.data ?? [], cleared.map, "review_log", (r) => r.created_at);
  const label: Record<string, string> = { approved: "Auto-approved", needs_review: "Sent to you", error: "Couldn't check: sent to you", skipped: "Skipped", fixing: "Fixing, will check again" };
  if (!list.length) return <p className="mt-1 text-sm text-muted">No automatic reviews yet.</p>;
  return (
    <ul className="mt-2 max-w-3xl divide-y divide-line rounded-xl border border-line bg-surface text-sm">
      {list.map((r) => {
        const title = (Array.isArray(r.content_projects) ? r.content_projects[0] : r.content_projects)?.title ?? "Package";
        return (
          <li key={r.id} className="px-4 py-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <Link to={`/content/${r.project_id}`} className="font-medium text-ink underline-offset-2 hover:underline">{title}</Link>
              <span className={`rounded-md px-2 py-0.5 text-xs ${r.verdict === "approved" ? "bg-penny-soft text-penny" : r.verdict === "skipped" ? "bg-sunken text-muted" : "bg-gold/15 text-ink"}`}>{label[r.verdict] ?? r.verdict}</span>
            </div>
            <p className="text-xs text-muted">{new Date(r.created_at).toLocaleString()}{r.reviewer ? ` · ${r.reviewer}` : ""}{r.confidence != null ? ` · ${Math.round(Number(r.confidence) * 100)}% confident` : ""}{r.posts_scheduled ? ` · ${r.posts_scheduled} post(s) scheduled` : ""}</p>
            {r.fix && <p className="mt-1 text-xs text-ink">🔧 {r.verdict === "fixing" ? `Attempt ${r.attempt}: ` : "Fixed: "}{r.fix}</p>}
            {r.reasons?.slice(0, 3).map((x) => <p key={x} className="mt-1 text-xs text-ink">• {x}</p>)}
          </li>
        );
      })}
    </ul>
  );
}
