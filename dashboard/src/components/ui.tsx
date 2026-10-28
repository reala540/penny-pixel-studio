import { createContext, ReactNode, useCallback, useContext, useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { HOST, statusText, statusTone, type Tone } from "../lib/format";
import { friendlyError } from "../lib/state";
import type { Channel } from "../lib/types";

const TONE: Record<Tone, string> = {
  good: "bg-penny-soft text-penny",
  warn: "bg-gold/20 text-ink",
  bad: "bg-alert-soft text-alert",
  info: "bg-pixel-soft text-pixel",
  neutral: "bg-sunken text-muted",
};

export function StatusBadge({ status }: { status: string }) {
  return (
    <span className={`inline-flex items-center rounded-md px-2 py-0.5 text-xs font-medium ${TONE[statusTone(status)]}`}>
      {statusText(status)}
    </span>
  );
}

/** The host marker: Pixel is a square (screen), Penny a circle (coin). Shape + colour, so it never relies on colour alone. */
export function HostMark({ channel, size = 10 }: { channel: Channel; size?: number }) {
  const common = { width: size, height: size, display: "inline-block", flexShrink: 0 } as const;
  return channel === "ai" ? (
    <span aria-hidden style={{ ...common, borderRadius: 2 }} className="bg-cyan" />
  ) : (
    <span aria-hidden style={{ ...common, borderRadius: 999 }} className="bg-gold" />
  );
}

export function HostTag({ channel }: { channel: Channel }) {
  return (
    <span className="inline-flex items-center gap-1.5 text-xs font-medium text-muted">
      <HostMark channel={channel} />
      {HOST[channel].name}
    </span>
  );
}

export function PageHeader({ title, intro, actions }: { title: string; intro?: string; actions?: ReactNode }) {
  return (
    <header className="mb-6 flex flex-wrap items-end justify-between gap-4">
      <div className="max-w-2xl">
        <h1 className="font-display text-2xl font-bold sm:text-3xl">{title}</h1>
        {intro && <p className="mt-1 text-muted">{intro}</p>}
      </div>
      {actions && <div className="flex flex-wrap gap-2">{actions}</div>}
    </header>
  );
}

export function Empty({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="rounded-xl border border-dashed border-line px-6 py-10 text-center">
      <p className="font-display text-lg font-semibold">{title}</p>
      {children && <div className="mx-auto mt-2 max-w-md text-sm text-muted">{children}</div>}
    </div>
  );
}

export function ErrorNote({ error, onRetry, retrying }: { error: unknown; onRetry?: () => void; retrying?: boolean }) {
  if (!error) return null;
  return (
    <p role="alert" className="flex flex-wrap items-center gap-2 rounded-lg bg-alert-soft px-3 py-2 text-sm text-alert">
      <span>{friendlyError(error)}</span>
      {onRetry && <button type="button" className="rounded-md border border-alert/40 px-2 py-0.5 text-xs font-semibold" onClick={onRetry} disabled={retrying}>
        {retrying ? "Retrying…" : "Retry"}</button>}
    </p>
  );
}

/** The state of something the page needs to know, when it isn't a confirmed answer: loading, offline or failed (with Retry).
 *  Renders nothing once it's confirmed. Never says "off", "none" or "not linked" on its own. */
export function NotConfirmed({ q, what, compact = false }: { q: { isLoading: boolean; isError: boolean; error: unknown; isFetching?: boolean; refetch: () => unknown; dataUpdatedAt?: number }; what: string; compact?: boolean }) {
  const online = typeof navigator === "undefined" || navigator.onLine !== false;
  if (!q.isError && !q.isLoading) return null;
  if (q.isLoading && !q.isError) return compact ? <span className="text-xs text-muted">Checking {what}…</span> : <Loading label={`Loading ${what}`} />;
  const stale = q.dataUpdatedAt ? ` Showing what was known at ${new Date(q.dataUpdatedAt).toLocaleTimeString()}.` : "";
  const text = online ? `Couldn't load ${what}: ${friendlyError(q.error)}${stale}` : `You're offline, so ${what} can't be checked.${stale}`;
  return (
    <p role="alert" className={`flex flex-wrap items-center gap-2 rounded-lg bg-alert-soft text-alert ${compact ? "px-2 py-1 text-xs" : "px-3 py-2 text-sm"}`}>
      <span>{text}</span>
      <button type="button" className="rounded-md border border-alert/40 px-2 py-0.5 text-xs font-semibold" onClick={() => q.refetch()} disabled={q.isFetching}>
        {q.isFetching ? "Retrying…" : "Retry"}</button>
    </p>
  );
}

/** Report an error from anywhere (shown as a toast by ToastProvider). */
export function reportError(error: unknown): void {
  window.dispatchEvent(new CustomEvent("studio-error", { detail: friendlyError(error) }));
}

export function Loading({ label = "Loading" }: { label?: string }) {
  return (
    <div role="status" className="space-y-2 py-4" aria-label={label}>
      {[0, 1, 2].map((i) => (
        <div key={i} className="h-4 animate-pulse rounded bg-sunken" style={{ width: `${90 - i * 18}%` }} />
      ))}
    </div>
  );
}

// --------------------------------------------------------------------- toasts

interface ToastAction {
  label: string;
  run: () => void | Promise<void>;
}

interface Toast {
  id: number;
  text: string;
  tone: "good" | "bad";
  action?: ToastAction;
}

type Push = (text: string, tone?: "good" | "bad", action?: ToastAction) => void;
const ToastCtx = createContext<Push>(() => {});

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const push = useCallback<Push>((text, tone = "good", action) => {
    const id = Date.now() + Math.random();
    const shown = tone === "bad" ? friendlyError(text) : text;
    setToasts((t) => {
      if (tone !== "bad") return [...t, { id, text: shown, tone, action }];
      // one failure, one message: a specific "X wasn't done: reason" replaces the general "reason" toast for the same error
      const recent = (x: Toast) => x.tone === "bad" && id - x.id < 3000;
      if (t.some((x) => recent(x) && x.text.includes(shown))) return t;
      return [...t.filter((x) => !(recent(x) && shown.includes(x.text))), { id, text: shown, tone, action }];
    });
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), action ? 9000 : tone === "bad" ? 9000 : 4500);  // longer for errors and Undo
  }, []);
  const dismiss = (id: number) => setToasts((t) => t.filter((x) => x.id !== id));
  useEffect(() => {
    const onError = (e: Event) => push(String((e as CustomEvent).detail), "bad");
    window.addEventListener("studio-error", onError);
    return () => window.removeEventListener("studio-error", onError);
  }, [push]);
  return (
    <ToastCtx.Provider value={push}>
      {children}
      <div aria-live="polite" role="status" className="pointer-events-none fixed bottom-20 right-4 z-50 flex max-w-[calc(100vw-2rem)] flex-col gap-2 md:bottom-6">
        {toasts.map((t) => (
          <div key={t.id} className={`pointer-events-auto flex items-center gap-3 rounded-lg px-4 py-2.5 text-sm shadow-lg ${t.tone === "good" ? "bg-ink text-surface" : "bg-alert text-surface"}`}>
            <span>{t.text}</span>
            {t.action && (
              <button className="rounded-md border border-surface/40 px-2 py-0.5 text-xs font-semibold hover:bg-surface/10"
                onClick={async () => { dismiss(t.id); try { await t.action!.run(); } catch (e) { push(`${t.action!.label} didn't work: ${friendlyError(e)}`, "bad"); } }}>{t.action.label}</button>
            )}
          </div>
        ))}
      </div>
    </ToastCtx.Provider>
  );
}

export function useToast() {
  return useContext(ToastCtx);
}

export function Confirm({ open, title, body, confirmLabel, danger, onConfirm, onCancel, confirmDisabled }: {
  open: boolean; title: string; body: ReactNode; confirmLabel: string; danger?: boolean; onConfirm: () => void; onCancel: () => void;
  confirmDisabled?: boolean;
}) {
  if (!open) return null;
  // Rendered at the end of <body> so a dialog opened from inside a table or list stays valid HTML.
  return createPortal(
    <div className="fixed inset-0 z-40 flex items-end justify-center bg-ink/40 p-4 sm:items-center" onClick={onCancel}>
      <div role="dialog" aria-modal="true" aria-labelledby="confirm-title" className="w-full max-w-md rounded-xl bg-surface p-5 shadow-xl" onClick={(e) => e.stopPropagation()}
        onKeyDown={(e) => e.key === "Escape" && onCancel()}>
        <h2 id="confirm-title" className="font-display text-lg font-semibold">{title}</h2>
        <div className="mt-2 text-sm text-muted">{body}</div>
        <div className="mt-5 flex justify-end gap-2">
          <button className="btn-quiet" onClick={onCancel} autoFocus>Cancel</button>
          <button className={danger ? "btn-danger" : "btn-primary"} onClick={onConfirm} disabled={confirmDisabled}>{confirmLabel}</button>
        </div>
      </div>
    </div>,
    document.body,
  );
}
