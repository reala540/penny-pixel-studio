import { useFormDraft } from "../lib/formDraft";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, RotateCcw, TriangleAlert, X } from "lucide-react";
import { useState } from "react";
import { missingFunction, useAccounts, useSetting, useTimezone } from "../lib/api";
import { PLATFORM_NAME } from "../lib/format";
import { DAY_LABEL, DAYS, Day, draftFrom, KINDS, payload, ScheduleDraft, totalPerWeek, warnings, weekPreview } from "../lib/schedule";
import { supabase } from "../lib/supabase";
import type { Account } from "../lib/types";
import { Confirm, Loading, NotConfirmed, useToast } from "./ui";

/** Settings → Posting schedule: days, times, posts per week and pause, per account, with a weekly preview. */
export default function PostingSchedule() {
  const accounts = useAccounts();
  const timezone = useSetting<string>("timezone", "Africa/Nairobi");
  const tz = timezone.data;
  if (accounts.isLoading) return <Loading />;
  if (!accounts.isSuccess) return <NotConfirmed q={accounts} what="account schedules" />;
  if (!timezone.isSuccess) return <NotConfirmed q={timezone} what="the schedule timezone" />;
  return (
    <div className="space-y-5">
      <p className="text-sm text-muted">Times are in {tz}. Changes apply from the next production run; posts already planned stay where they are unless you tick "move".</p>
      {(accounts.data ?? []).map((a) => <AccountSchedule key={`${a.id}:${JSON.stringify(a.weekly_targets)}:${a.enabled}`} account={a} />)}
    </div>
  );
}

function DayPicker({ value, onChange, label }: { value: Day[]; onChange: (d: Day[]) => void; label: string }) {
  return (
    <fieldset className="text-sm">
      <legend className="text-muted">{label}</legend>
      <div className="mt-1.5 flex flex-wrap gap-1.5">
        {DAYS.map((d) => {
          const on = value.includes(d);
          return <button key={d} type="button" aria-pressed={on} onClick={() => onChange(on ? value.filter((x) => x !== d) : DAYS.filter((x) => x === d || value.includes(x)))}
            className={`rounded-lg border px-2.5 py-1 text-sm ${on ? "border-ink bg-ink text-surface" : "border-line text-muted hover:text-ink"}`}>{DAY_LABEL[d]}</button>;
        })}
      </div>
    </fieldset>
  );
}

function TimesPicker({ value, onChange, label }: { value: string[]; onChange: (t: string[]) => void; label: string }) {
  const [add, setAdd] = useState("");
  return (
    <fieldset className="text-sm">
      <legend className="text-muted">{label}</legend>
      <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
        {value.map((t) => (
          <span key={t} className="inline-flex items-center gap-1 rounded-lg border border-line px-2 py-1 tabular">
            {t}<button type="button" aria-label={`Remove ${t}`} className="text-muted hover:text-alert" onClick={() => onChange(value.filter((x) => x !== t))}><X size={13} /></button>
          </span>
        ))}
        {value.length < 4 && (
          <span className="inline-flex items-center gap-1">
            <input type="time" aria-label={`Add a time to ${label.toLowerCase()}`} className="field w-auto py-1" value={add} onChange={(e) => setAdd(e.target.value)} />
            <button type="button" className="btn-quiet px-2 py-1" disabled={!add || value.includes(add)} onClick={() => { onChange([...value, add].sort()); setAdd(""); }}>
              <Plus size={14} aria-hidden />Add</button>
          </span>
        )}
      </div>
    </fieldset>
  );
}

function AccountSchedule({ account }: { account: Account }) {
  const qc = useQueryClient();
  const toast = useToast();
  const defaults = useSetting<Record<string, Record<string, unknown>>>("posting_schedule_defaults", {}).data ?? {};
  const initial = draftFrom(account.platform, account.enabled, account.weekly_targets ?? {});
  const [d, setD, draft] = useFormDraft<ScheduleDraft>(`schedule:${account.id}`, initial);
  const [move, setMove] = useState(false);
  const [askMove, setAskMove] = useState(false);
  const tz = useTimezone();
  // preview: exactly which posts "move" would touch (future, not yet published or publishing)
  const affected = useQuery({
    queryKey: ["schedule-move-preview", account.id], enabled: askMove,
    queryFn: async () => {
      const { count, error } = await supabase.from("scheduled_posts").select("id", { count: "exact", head: true })
        .eq("social_account_id", account.id).in("status", ["pending_approval", "scheduled"]).gt("scheduled_at", new Date().toISOString());
      if (error) throw new Error(error.message);
      return count ?? 0;
    },
  });
  const changed = JSON.stringify(d) !== JSON.stringify(initial);
  const save = useMutation({
    mutationFn: async () => {
      const args = { p_account_id: account.id, p_schedule: payload(account.platform, d), p_move: move };
      let response = await supabase.rpc("save_posting_schedule", { ...args, p_expected: { weekly_targets: account.weekly_targets, enabled: account.enabled } });
      if (missingFunction(response.error)) response = await supabase.rpc("set_posting_schedule", args);
      const {data,error} = response;
      if (error) throw new Error(error.message);
      return data as { moved_posts: number };
    },
    onSuccess: (r) => {
      toast(`${account.label} schedule saved${r.moved_posts ? ` · ${r.moved_posts} waiting post(s) moved` : ""}`);
      qc.invalidateQueries({ queryKey: ["accounts"] });
      qc.invalidateQueries({ queryKey: ["posts"] });
    },
    onError: (e) => toast((e as Error).message, "bad"),
  });
  const set = (patch: Partial<ScheduleDraft>) => setD((x) => ({ ...x, ...patch }));
  const kinds = KINDS[account.platform];
  const week = weekPreview(account.platform, d);
  const warn = warnings(account.platform, d);
  const def = defaults[account.label];
  return (
    <section aria-labelledby={`sched-${account.id}`} className="rounded-xl border border-line bg-surface p-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h3 id={`sched-${account.id}`} className="font-display text-base font-semibold">{account.label} <span className="text-sm font-normal text-muted">· {PLATFORM_NAME[account.platform]}</span></h3>
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" checked={d.enabled} onChange={(e) => set({ enabled: e.target.checked })} />
          {d.enabled ? "Posting" : "Paused"}
        </label>
      </div>
      <div className="mt-3 grid gap-4 lg:grid-cols-2">
        <div className="space-y-3">
          <DayPicker label={account.platform === "youtube" ? "Long-video days" : "Posting days"} value={d.posting_days} onChange={(v) => set({ posting_days: v })} />
          <TimesPicker label={account.platform === "youtube" ? "Long-video times" : "Posting times"} value={d.posting_times} onChange={(v) => set({ posting_times: v })} />
          {account.platform === "youtube" && <>
            <DayPicker label="Shorts days" value={d.shorts_days} onChange={(v) => set({ shorts_days: v })} />
            <TimesPicker label="Shorts times" value={d.shorts_times} onChange={(v) => set({ shorts_times: v })} />
          </>}
          <div className="flex flex-wrap gap-3">
            {kinds.map((k) => (
              <label key={k.kind} className="text-sm"><span className="block text-muted">{k.label} per week</span>
                <input type="number" min={0} max={14} className="field mt-1 w-24 tabular" value={d.targets[k.kind] ?? 0}
                  onChange={(e) => set({ targets: { ...d.targets, [k.kind]: Math.min(14, Math.max(0, Math.round(Number(e.target.value) || 0))) } })} />
              </label>
            ))}
          </div>
        </div>
        <div>
          <p className="text-sm text-muted">This week would look like this · <span className="font-medium text-ink">{totalPerWeek(account.platform, d)} posts</span></p>
          <ol className="mt-2 grid grid-cols-7 gap-1 text-center text-xs">
            {DAYS.map((day) => (
              <li key={day} className="rounded-lg border border-line px-1 py-1.5">
                <span className="block font-medium">{DAY_LABEL[day]}</span>
                {week[day].length === 0 ? <span className="text-muted">–</span> : week[day].map((s, i) => (
                  <span key={i} className="mt-1 block rounded bg-sunken px-0.5 py-0.5 tabular" title={s.label}>{s.time}<span className="block text-[10px] text-muted">{s.label}</span></span>
                ))}
              </li>
            ))}
          </ol>
          {warn.length > 0 && (
            <ul className="mt-3 space-y-1">
              {warn.map((w) => <li key={w} className="flex items-start gap-1.5 text-xs text-ink"><TriangleAlert size={13} className="mt-0.5 shrink-0 text-gold" aria-hidden />{w}</li>)}
            </ul>
          )}
        </div>
      </div>
      {draft.message && <p role="status" className="mt-3 text-sm text-muted">{draft.message}</p>}
      <div className="mt-4 flex flex-wrap items-center gap-3 border-t border-line pt-3">
        <button className="btn-primary" disabled={!changed || save.isPending || draft.conflict} onClick={() => move ? setAskMove(true) : save.mutate()}>{save.isPending ? "Saving…" : "Save schedule"}</button>
        {changed && <button className="btn-quiet" onClick={draft.reset}>Undo changes</button>}
        {def && <button className="btn-quiet" onClick={() => setD(draftFrom(account.platform, d.enabled, def))}><RotateCcw size={14} aria-hidden />Reset to default</button>}
        <label className="flex items-center gap-2 text-sm text-muted">
          <input type="checkbox" checked={move} onChange={(e) => setMove(e.target.checked)} />Also move posts already waiting to the new times
        </label>
      </div>
      <Confirm open={askMove} title={`Move waiting posts for ${account.label}?`} body={`This saves the schedule and moves ${affected.isSuccess ? `${affected.data} future post${affected.data === 1 ? "" : "s"}` : affected.isError ? "this account's future waiting posts (couldn't count them just now)" : "this account's future waiting posts (counting…)"} to the new slots. Published and currently publishing posts stay unchanged. Slot times are in ${tz}; changing the studio's timezone later (Appearance & region) changes future slots, not posts that already have a time.`} confirmLabel="Save and move" onCancel={() => setAskMove(false)} onConfirm={() => { setAskMove(false); save.mutate(); }} />
    </section>
  );
}
