import { useEffect } from "react";
import { Link } from "react-router-dom";
import { draftLabel, draftState, draftUrl, useDraftFacts } from "../lib/draftStatus";
import { removeDraft, saveDraft, useDrafts, useOwnerId, type CreateDraft } from "../lib/drafts";
import { useToast } from "./ui";

/** Unfinished "Create content" work on this device, checked against the database. Continue only opens the page. */
export default function DraftList({ title = "Continue where you left off", exclude, compact = false }: { title?: string; exclude?: string | null; compact?: boolean }) {
  const owner = useOwnerId();
  const toast = useToast();
  const drafts = useDrafts().filter((d) => d.id !== exclude);
  const facts = useDraftFacts(drafts);
  const states = drafts.map((d) => [d, draftState(d, facts.data)] as const);

  // a draft whose package is made is finished: it's in Content now, so it leaves this list
  const doneIds = states.filter(([, s]) => s.state === "done").map(([d]) => d.id).join(",");
  useEffect(() => { if (doneIds) doneIds.split(",").forEach((id) => removeDraft(owner, id)); }, [doneIds, owner]);

  const discard = (d: CreateDraft) => {
    removeDraft(owner, d.id);
    toast("Draft removed", "good", { label: "Undo", run: () => { if (owner) saveDraft(owner, d, null, true); } });
  };
  const shown = states.filter(([, s]) => s.state !== "done");
  if (!shown.length) return null;
  return (
    <section aria-labelledby="drafts-title" className={compact ? "" : "mb-6"}>
      <h2 id="drafts-title" className="section-title mb-2">{title}</h2>
      <ul className="divide-y divide-line rounded-xl border border-line bg-surface">
        {shown.map(([d, s]) => (
          <li key={d.id} className="flex flex-wrap items-center justify-between gap-2 px-4 py-3 text-sm">
            <span className="min-w-0 flex-1">
              <span className={s.state === "failed" || s.state === "missing" ? "text-alert" : ""}>{draftLabel(d, s)}</span>
              <span className="block text-xs text-muted">Saved on this device {new Date(d.updatedAt).toLocaleString()}{facts.isError ? " · couldn't check the studio just now" : ""}</span>
            </span>
            <span className="flex gap-2">
              <Link className={s.state === "failed" ? "btn-primary" : "btn-quiet"} to={draftUrl(d, s)}>
                {s.state === "failed" ? "Fix problem" : s.state === "making" ? "View progress" : "Continue"}</Link>
              {s.state !== "making" && <button type="button" className="btn-quiet" onClick={() => discard(d)} aria-label={`Remove draft ${d.ideaTitle ?? ""}`.trim()}>Remove</button>}
            </span>
          </li>
        ))}
      </ul>
    </section>
  );
}
