export function relativeTime(value: string, now = Date.now()): string {
  const seconds = Math.max(0, Math.round((now - Date.parse(value)) / 1000));
  if (seconds < 60) return `${seconds}s ago`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
  return new Date(value).toLocaleDateString("en-GB", { day: "numeric", month: "short" });
}

export function compact(value: number): string {
  return value > 999 ? `${(value / 1000).toFixed(1)}k` : String(value);
}

export function workflowLabel(value: string): string {
  return value === "produce" ? "Production" : value[0].toUpperCase() + value.slice(1);
}

export function jobLabel(value: string): string {
  return value.replace(/^run_/, "").replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase());
}

/** A linked row's title, whether the client returns the embed as one object or a one-item list. */
export function embedTitle(embed: { title: string } | { title: string }[] | null | undefined): string | undefined {
  return (Array.isArray(embed) ? embed[0] : embed)?.title;
}
