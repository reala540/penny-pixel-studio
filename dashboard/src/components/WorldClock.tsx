import { useQuery } from "@tanstack/react-query";
import { must } from "../lib/api";
import { clockFace, isValidZone, KENYA_TZ, placeName, useNow } from "../lib/clock";
import { known, useOnline } from "../lib/state";
import { supabase } from "../lib/supabase";

/** The studio timezone exactly as saved on the account: null when it was never saved (the studio then uses its
 *  default, Africa/Nairobi). Its key sits under ["setting","timezone"], so saving the timezone refreshes it at once,
 *  in this tab and in others. */
function useSavedTimezone() {
  return useQuery({
    queryKey: ["setting", "timezone", "saved"],
    queryFn: async () => {
      const rows = (await must(supabase.from("settings").select("value").eq("key", "timezone"))) as { value: unknown }[];
      return rows.length ? rows[0].value : null;
    },
  });
}

function Face({ label, tz, now, note }: { label: string; tz: string; now: Date; note?: string }) {
  const f = clockFace(now, tz);
  return (
    <div className="min-w-0" title={`${label}: ${tz}${note ? ` (${note})` : ""}`}>
      <p className="truncate text-[11px] font-medium uppercase tracking-wide text-muted">{label}{note ? ` · ${note}` : ""}</p>
      <p className="flex min-w-0 flex-wrap items-baseline gap-x-1.5 leading-tight">
        <time dateTime={f.iso} className="tabular font-mono text-sm font-semibold text-ink">{f.time}</time>
        <span className="truncate text-xs text-muted">{f.date} · {f.zone}</span>
      </p>
      <p className="truncate text-[11px] text-muted">{placeName(tz)}</p>
    </div>
  );
}

function Unavailable({ label, text, retry }: { label: string; text: string; retry?: () => void }) {
  return (
    <div className="min-w-0" role="status">
      <p className="truncate text-[11px] font-medium uppercase tracking-wide text-muted">{label}</p>
      <p className="text-xs text-muted">{text}{retry && <> <button type="button" className="underline hover:text-ink" onClick={retry}>Retry</button></>}</p>
    </div>
  );
}

/** Studio time (the account's saved timezone) and Kenyan time, from one shared instant, every second. */
export default function WorldClock() {
  const now = useNow();
  const online = useOnline();
  const q = useSavedTimezone();
  const saved = known(q, online);
  const tz = saved.state === "confirmed" ? saved.value : saved.state === "failed" || saved.state === "offline" ? saved.last : undefined;

  let studio;
  if (tz === undefined) {
    studio = saved.state === "loading" ? <Unavailable label="Studio time" text="Loading…" />
      : <Unavailable label="Studio time" text={saved.state === "offline" ? "Unavailable while offline" : "Unavailable: couldn't load settings."}
          retry={saved.state === "failed" ? () => q.refetch() : undefined} />;
  } else if (tz === null) {
    studio = <Face label="Studio time" tz={KENYA_TZ} now={now} note="default" />;
  } else if (!isValidZone(tz)) {
    studio = <Unavailable label="Studio time" text="Unavailable: the saved timezone isn't recognised. Choose one in Settings." />;
  } else {
    studio = <Face label="Studio time" tz={tz} now={now} />;
  }

  return (
    <div role="group" aria-label="World clock" className="grid grid-cols-2 gap-3 sm:flex sm:items-center sm:gap-6">
      {studio}
      <div className="hidden h-8 w-px bg-line sm:block" aria-hidden />
      <Face label="Kenyan time" tz={KENYA_TZ} now={now} />
    </div>
  );
}
