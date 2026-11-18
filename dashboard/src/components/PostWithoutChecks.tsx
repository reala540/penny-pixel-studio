// The owner's "Full auto-posting" switch: settings.publish_without_checks = {on, auto_approve}. ON: the engine
// (review/owner_auto.py) approves every finished package for the owner, and posts go out without the final fact check
// and freshness stop (publish/runner.py checks_off); the website publishes flagged articles with a reader note.
// OFF: packages wait for the owner's approval and the checks apply again from the next run.
// Accounts, licences, the publishing pause and duplicate protection always apply.

import { ShieldCheck, ShieldOff } from "lucide-react";
import { useState } from "react";
import { useSaveSetting, useSetting } from "../lib/api";
import { Confirm, NotConfirmed, useToast } from "./ui";

export const SETTING = "publish_without_checks";

/** Same rule as the engine's checks_off: true, or {on: true} without an end time or with an end time still ahead. */
export function checksOff(v: unknown, now: Date = new Date()): boolean {
  if (v === true) return true;
  if (v && typeof v === "object" && (v as { on?: unknown }).on) {
    const until = (v as { until?: string }).until;
    if (!until) return true;
    const t = Date.parse(until);
    return Number.isFinite(t) && t > now.getTime();
  }
  return false;
}

/** Same rule as the engine's full_auto: checks off and auto_approve on. */
export function fullAuto(v: unknown, now: Date = new Date()): boolean {
  return checksOff(v, now) && Boolean(v && typeof v === "object" && (v as { auto_approve?: unknown }).auto_approve === true);
}

export default function PostWithoutChecks({ compact = false }: { compact?: boolean }) {
  const setting = useSetting<unknown>(SETTING, null);
  const save = useSaveSetting();
  const toast = useToast();
  const [confirm, setConfirm] = useState(false);
  const on = fullAuto(setting.data);
  const partly = !on && checksOff(setting.data);   // checks off but approvals still manual (set before this switch existed)
  const until = (setting.data as { until?: string } | null)?.until;

  const change = (next: boolean) => save.mutate(
    { key: SETTING, value: { on: next, auto_approve: next, set_by: "owner", set_at: new Date().toISOString() } },
    { onSuccess: () => toast(next ? "Full auto-posting: ON" : "Full auto-posting: OFF. You approve, and the checks are back on"),
      onError: (e) => toast((e as Error).message, "bad") });

  if (!setting.isSuccess) return <NotConfirmed q={setting} what="the last-minute checks switch" compact={compact} />;
  return (
    <div className={compact ? "flex flex-wrap items-center gap-3" : "flex flex-wrap items-center gap-3"}>
      <button type="button" role="switch" aria-checked={on} disabled={save.isPending}
        onClick={() => (on ? change(false) : setConfirm(true))}
        className={`relative inline-flex h-7 w-12 shrink-0 items-center rounded-full border transition-colors ${on ? "border-alert bg-alert" : "border-line bg-sunken"} disabled:opacity-50`}>
        <span className={`inline-block h-5 w-5 rounded-full bg-surface shadow transition-transform ${on ? "translate-x-6" : "translate-x-1"}`} />
        <span className="sr-only">Full auto-posting</span>
      </button>
      <span className="flex items-center gap-2 text-sm font-semibold text-ink" aria-live="polite">
        {on ? <ShieldOff size={16} aria-hidden /> : <ShieldCheck size={16} aria-hidden />}
        Full auto-posting: {on ? "ON" : "OFF"}
      </span>
      {partly && <span className="text-xs text-muted">(last-minute checks are off, but you still approve)</span>}
      {!compact && <span className="text-sm text-muted">
        {on ? `Every finished package is approved for you and posts at its times, without the last-minute checks${until ? ` (until ${new Date(until).toLocaleString()})` : " (until you switch it off)"}.`
            : "You approve each package, and posts are checked one last time before they go out."}
      </span>}
      <Confirm open={confirm} title="Turn on Full auto-posting?" confirmLabel="Turn on"
        body={<>
          <p>The studio will <strong>approve every finished package for you</strong> (including its Shorts) and post everything at
            its scheduled times <strong>without</strong> the final fact check and the "content expired" freshness stop. Posts
            those checks stopped earlier are put back on the schedule. The website also publishes articles its checks would
            leave out, with a note telling readers they weren't fully checked.</p>
          <p className="mt-2">Still applied: the right accounts, licences, the publishing pause and duplicate protection.
            It stays on until you switch it off here. OFF puts everything back to normal: you approve, and the checks apply.</p>
        </>}
        onConfirm={() => { setConfirm(false); change(true); }} onCancel={() => setConfirm(false)} />
    </div>
  );
}
