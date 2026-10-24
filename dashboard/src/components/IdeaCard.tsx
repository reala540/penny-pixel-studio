import { Archive, Bookmark, BookmarkCheck, ChevronDown, ExternalLink, RotateCcw, Send, Sparkles, X } from "lucide-react";
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { CONFIDENCE_TEXT, scoreBreakdown, SENSITIVITY_TEXT } from "../lib/ideas";
import { useIdeaActions } from "../lib/ideasApi";
import { safeUrl } from "../lib/format";
import type { GeneratedIdea } from "../lib/types";
import { useToast } from "./ui";

const CONF_TONE: Record<GeneratedIdea["confidence"], string> = {
  high: "bg-penny-soft text-penny", medium: "bg-pixel-soft text-pixel", low: "bg-sunken text-muted",
  unverified: "bg-alert-soft text-alert",
};
const STATUS_TEXT: Record<GeneratedIdea["status"], string> = {
  new: "To use", saved: "Saved", rejected: "Not for me", sent_to_studio: "Used", archived: "Archived",
};

function Chip({ className, children }: { className: string; children: React.ReactNode }) {
  return <span className={`inline-flex items-center rounded-md px-2 py-0.5 text-xs font-medium ${className}`}>{children}</span>;
}

/** `onUse` replaces "Create from this idea" (the Create flow selects the idea instead of navigating). */
export default function IdeaCard({ idea, defaultOpen = false, onUse, useLabel = "Use this idea" }: {
  idea: GeneratedIdea; defaultOpen?: boolean; onUse?: (idea: GeneratedIdea) => void; useLabel?: string;
}) {
  const [open, setOpen] = useState(defaultOpen);
  const [refining, setRefining] = useState(false);
  const [note, setNote] = useState("");
  const navigate = useNavigate();
  const toast = useToast();
  const { setStatus, refine } = useIdeaActions();
  const busy = setStatus.isPending || refine.isPending;
  const parts = scoreBreakdown(idea);
  const fail = (e: unknown) => toast((e as Error).message, "bad");

  const use = () => (onUse ? onUse(idea) : navigate(`/create?${new URLSearchParams({
    step: "research", kind: "generated", id: idea.id, ...(idea.channel_slug === "ai" || idea.channel_slug === "money" ? { channel: idea.channel_slug } : {}),
  })}`));

  return (
    <article className="rounded-xl border border-line bg-surface p-4" aria-labelledby={`idea-${idea.id}`}>
      <div className="flex items-start gap-3">
        <span className="mt-0.5 inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-sunken text-xs font-semibold text-ink" aria-label={`Rank ${idea.rank}`}>{idea.rank}</span>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-start justify-between gap-2">
            <h3 id={`idea-${idea.id}`} className="font-display text-base font-semibold leading-snug text-ink">{idea.title}</h3>
            <span className="shrink-0 rounded-lg bg-ink px-2 py-1 text-xs font-semibold tabular-nums text-surface" title="Weighted assessment score, not a prediction of success">
              {Number(idea.total).toFixed(0)}<span className="font-normal opacity-70">/100</span>
            </span>
          </div>
          <div className="mt-1.5 flex flex-wrap gap-1.5">
            <Chip className={CONF_TONE[idea.confidence]}>{CONFIDENCE_TEXT[idea.confidence]}</Chip>
            {idea.sensitivity !== "none" && <Chip className="bg-gold/15 text-ink">{SENSITIVITY_TEXT[idea.sensitivity]}</Chip>}
            {idea.category && <Chip className="bg-sunken text-muted">{idea.category}</Chip>}
            {idea.channel_slug && <Chip className="bg-sunken text-muted">{idea.channel_slug === "ai" ? "Pixel · AI" : idea.channel_slug === "money" ? "Penny · Money" : "Both channels"}</Chip>}
            {idea.status !== "new" && <Chip className="bg-sunken text-ink">{STATUS_TEXT[idea.status]}</Chip>}
          </div>
          <p className="mt-2 text-sm leading-6 text-ink">{idea.summary}</p>
          <p className="mt-1 text-xs text-muted">
            For {idea.audience}{idea.markets.length ? ` · ${idea.markets.join(", ")}` : ""}{idea.suggested_format ? ` · ${idea.suggested_format}` : ""}
          </p>
        </div>
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-2">
        <button className="btn-primary" onClick={use} disabled={busy || idea.status === "rejected"}><Send size={14} aria-hidden />{onUse ? useLabel : "Create from this idea"}</button>
        {idea.status === "saved"
          ? <button className="btn-quiet" disabled={busy} onClick={() => setStatus.mutate({ idea, status: "new" }, { onError: fail })}><BookmarkCheck size={14} aria-hidden />Saved</button>
          : <button className="btn-quiet" disabled={busy || idea.status === "rejected"} onClick={() => setStatus.mutate({ idea, status: "saved" }, { onSuccess: () => toast("Saved to your Idea Library"), onError: fail })}><Bookmark size={14} aria-hidden />Save</button>}
        <button className="btn-quiet" disabled={busy || idea.status === "rejected"} onClick={() => setRefining(!refining)} aria-expanded={refining}><Sparkles size={14} aria-hidden />Refine</button>
        {idea.status === "rejected"
          ? <button className="btn-quiet" disabled={busy} onClick={() => setStatus.mutate({ idea, status: "new" }, { onError: fail })}><RotateCcw size={14} aria-hidden />Restore</button>
          : <button className="btn-quiet" disabled={busy} onClick={() => setStatus.mutate({ idea, status: "rejected" }, { onSuccess: () => toast("Marked Not for me. Future batches won't repeat it."), onError: fail })}><X size={14} aria-hidden />Not for me</button>}
        {idea.status !== "archived" && idea.status !== "new" && idea.status !== "rejected" &&
          <button className="btn-quiet" disabled={busy} onClick={() => setStatus.mutate({ idea, status: "archived" }, { onError: fail })}><Archive size={14} aria-hidden />Archive</button>}
        <button className="ml-auto inline-flex items-center gap-1 text-sm text-muted hover:text-ink" onClick={() => setOpen(!open)} aria-expanded={open}>
          Why this score <ChevronDown size={14} className={open ? "rotate-180" : ""} aria-hidden />
        </button>
      </div>

      {refining && (
        <form className="mt-3 flex flex-col gap-2 sm:flex-row" onSubmit={(e) => {
          e.preventDefault();
          if (note.trim().length < 4) return;
          refine.mutate({ idea, note }, { onSuccess: () => { toast("Refining… the improved version appears here in a few minutes."); setRefining(false); setNote(""); }, onError: fail });
        }}>
          <label className="flex-1"><span className="sr-only">How should this idea change?</span>
            <input className="field" value={note} maxLength={800} onChange={(e) => setNote(e.target.value)} placeholder="e.g. Make it practical for students in Kenya" />
          </label>
          <button className="btn-quiet" disabled={refine.isPending || note.trim().length < 4}>Refine idea</button>
        </form>
      )}

      {open && (
        <div className="mt-4 grid gap-4 border-t border-line pt-4 lg:grid-cols-2">
          <div>
            <h4 className="text-xs font-semibold uppercase tracking-wide text-muted">Score breakdown</h4>
            <ul className="mt-2 space-y-2">
              {parts.map((p) => (
                <li key={p.key}>
                  <div className="flex justify-between text-xs"><span className="text-ink">{p.label}</span><span className="tabular-nums text-muted">{p.points.toFixed(1)} / {p.max}</span></div>
                  <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-sunken" aria-hidden>
                    <div className={`h-full rounded-full ${p.key === "trend" ? "bg-pixel" : "bg-cyan"}`} style={{ width: `${(p.points / p.max) * 100}%` }} />
                  </div>
                </li>
              ))}
            </ul>
            <p className="mt-3 text-xs leading-5 text-muted">{idea.score_explanation}</p>
            {idea.sensitivity_note && <p className="mt-2 text-xs leading-5 text-ink">{idea.sensitivity_note}</p>}
            {idea.execution && <><h4 className="mt-4 text-xs font-semibold uppercase tracking-wide text-muted">Recommended approach</h4><p className="mt-1 text-sm text-ink">{idea.execution}</p></>}
            <p className="mt-3 text-xs text-muted">Proposed by {idea.generated_by ?? "unknown"} · assessed by {idea.assessed_by ?? "not assessed"}</p>
          </div>
          <div>
            <h4 className="text-xs font-semibold uppercase tracking-wide text-muted">Verified evidence</h4>
            {idea.trend_signals.length === 0 ? (
              <p className="mt-2 text-sm text-alert">Trend unverified: no current source supports this idea. Treat it as evergreen, not news.</p>
            ) : (
              <ul className="mt-2 space-y-2">
                {idea.trend_signals.map((s) => (
                  <li key={s.source_id} className="text-sm">
                    <a href={safeUrl(s.url)} target="_blank" rel="noopener noreferrer" className="inline-flex items-start gap-1 font-medium text-ink underline-offset-2 hover:underline">
                      {s.title}<ExternalLink size={12} className="mt-1 shrink-0" aria-hidden /><span className="sr-only">(opens in a new tab)</span>
                    </a>
                    <p className="text-xs text-muted">{s.observed} · {s.published_at ? `published ${s.published_at.slice(0, 10)}` : `seen ${s.retrieved_at.slice(0, 10)}`}</p>
                  </li>
                ))}
              </ul>
            )}
            {idea.assessment_notes?.trend_angle && (
              <><h4 className="mt-4 text-xs font-semibold uppercase tracking-wide text-muted">AI prediction (not evidence)</h4>
                <p className="mt-1 text-sm text-muted">{idea.assessment_notes.trend_angle}</p></>
            )}
          </div>
        </div>
      )}
    </article>
  );
}
