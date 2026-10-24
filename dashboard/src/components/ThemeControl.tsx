import { Monitor, Moon, Sun } from "lucide-react";
import { KeyboardEvent } from "react";
import { ThemePref, useTheme } from "../lib/theme";

const OPTIONS: { value: ThemePref; label: string; icon: typeof Sun }[] = [
  { value: "light", label: "Light", icon: Sun },
  { value: "dark", label: "Dark", icon: Moon },
  { value: "system", label: "System", icon: Monitor },
];

/** Light / Dark / System. A radio group: arrow keys move, the choice applies instantly. */
export default function ThemeControl({ compact = false }: { compact?: boolean }) {
  const [theme, set] = useTheme();
  const onKey = (e: KeyboardEvent<HTMLDivElement>) => {
    const i = OPTIONS.findIndex((o) => o.value === theme);
    const step = e.key === "ArrowRight" || e.key === "ArrowDown" ? 1 : e.key === "ArrowLeft" || e.key === "ArrowUp" ? -1 : 0;
    if (!step) return;
    e.preventDefault();
    const next = OPTIONS[(i + step + OPTIONS.length) % OPTIONS.length];
    set(next.value);
    (e.currentTarget.querySelector(`[data-value="${next.value}"]`) as HTMLButtonElement | null)?.focus();
  };
  return (
    <div role="radiogroup" aria-label="Colour theme" onKeyDown={onKey}
      className="inline-flex rounded-lg border border-line bg-sunken p-0.5">
      {OPTIONS.map(({ value, label, icon: Icon }) => {
        const on = theme === value;
        return (
          <button key={value} type="button" role="radio" aria-checked={on} tabIndex={on ? 0 : -1} data-value={value}
            onClick={() => set(value)} title={`${label} theme`}
            className={`inline-flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-xs font-medium transition-colors ${on ? "bg-surface text-ink shadow-sm" : "text-muted hover:text-ink"}`}>
            <Icon size={14} aria-hidden />
            <span className={compact ? "sr-only" : ""}>{label}</span>
          </button>
        );
      })}
    </div>
  );
}
