import { useToast } from "./ui";
import { useUiMode, type UiMode } from "../lib/uiMode";

const OPTIONS: [UiMode, string, string][] = [
  ["simple", "Simple", "The pages you need day to day"],
  ["advanced", "Advanced", "Everything, including AI keys and technical panels"],
];

/** Simple / Advanced menu switch. */
export default function ModeSwitch({ compact = false }: { compact?: boolean }) {
  const { mode, setMode, loading } = useUiMode();
  const toast = useToast();
  return (
    <div role="radiogroup" aria-label="Menu" className={compact ? "flex rounded-lg border border-line p-0.5" : "grid max-w-xl gap-2 sm:grid-cols-2"}>
      {OPTIONS.map(([value, label, hint]) => (
        <button key={value} type="button" role="radio" aria-checked={mode === value} disabled={loading}
          onClick={() => mode !== value && setMode(value).then(() => toast(`${label} menu`), (e) => toast((e as Error).message, "bad"))}
          className={compact
            ? `flex-1 rounded-md px-2 py-1 text-xs font-medium ${mode === value ? "bg-ink text-surface" : "text-muted hover:text-ink"}`
            : `rounded-xl border px-4 py-3 text-left ${mode === value ? "border-ink ring-1 ring-ink" : "border-line hover:bg-sunken"}`}>
          {compact ? label : <><span className="block text-sm font-semibold">{label}</span><span className="block text-xs text-muted">{hint}</span></>}
        </button>
      ))}
    </div>
  );
}
