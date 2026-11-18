// The owner's "post without last-minute checks" switch (settings.publish_without_checks), the same setting the engine
// reads in publish/runner.py checks_off(). ON: approved posts go out without the final fact check and the freshness
// stop, and the website publishes flagged articles with a reader note. OFF: those checks apply again at the next run.
// Approvals, accounts, licences, the publishing pause and duplicate protection always apply.

import { ShieldCheck, ShieldOff } from "lucide-react";
import { useState } from "react";
import { useSaveSetting, useSetting } from "../lib/api";
import { Confirm, NotConfirmed, useToast } from "./ui";

export const SETTING = "publish_without_checks";

/** Same rule as the engine: true, or {on: true} without an end time or with an end time still ahead. */
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

export default function PostWithoutChecks({ compact = false }: { compact?: boolean }) {
  const setting = useSetting<unknown>(SETTING, null);
  const save = useSaveSetting();
  const toast = useToast();
  const [confirm, setConfirm] = useState(false);
  const on = checksOff(setting.data);
  const until = (setting.data as { until?: string } | null)?.until;

  const change = (next: boolean) => save.mutate(
    { key: SETTING, value: { on: next, set_by: "owner", set_at: new Date().toISOString() } },
    { onSuccess: () => toast(next ? "Posting without last-minute checks: ON" : "Last-minute checks are back ON"),
      onError: (e) => toast((e as Error).message, "bad") });

  if (!setting.isSuccess) return <NotConfirmed q={setting} what="the last-minute checks switch" compact={compact} />;
  return (
    <div className={compact ? "flex flex-wrap items-center gap-3" : "flex flex-wrap items-center gap-3"}>
      <button type="button" role="switch" aria-checked={on} disabled={save.isPending}
        onClick={() => (on ? change(false) : setConfirm(true))}
        className={`relative inline-flex h-7 w-12 shrink-0 items-center rounded-full border transition-colors ${on ? "border-alert bg-alert" : "border-line bg-sunken"} disabled:opacity-50`}>
        <span className={`inline-block h-5 w-5 rounded-full bg-surface shadow transition-transform ${on ? "translate-x-6" : "translate-x-1"}`} />
        <span className="sr-only">Post without last-minute checks</span>
      </button>
      <span className="flex items-center gap-2 text-sm font-semibold text-ink" aria-live="polite">
        {on ? <ShieldOff size={16} aria-hidden /> : <ShieldCheck size={16} aria-hidden />}
        Post without last-minute checks: {on ? "ON" : "OFF"}
      </span>
      {!compact && <span className="text-sm text-muted">
        {on ? `Approved posts go out even if their facts are dated or the final fact check would stop them${until ? ` (until ${new Date(until).toLocaleString()})` : " (until you switch it off)"}.`
            : "Approved posts are checked one last time (final fact check and freshness) before they go out."}
      </span>}
      <Confirm open={confirm} title="Post without last-minute checks?" confirmLabel="Turn on"
        body={<>
          <p>Approved posts will go out at their times <strong>without</strong> the final fact check and the "content expired"
            freshness stop. The website will also publish articles its checks would leave out, with a note telling readers
            they weren't fully checked.</p>
          <p className="mt-2">Still applied: your approval, the right accounts, licences, the publishing pause and duplicate protection.
            It stays on until you switch it off here.</p>
        </>}
        onConfirm={() => { setConfirm(false); change(true); }} onCancel={() => setConfirm(false)} />
    </div>
  );
}
