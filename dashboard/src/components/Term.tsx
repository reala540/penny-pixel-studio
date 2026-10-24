import { CircleHelp } from "lucide-react";
import { ReactNode, useId, useState } from "react";
import { TERMS } from "../lib/labels";

/** A term with a small "?" that explains it in one sentence. */
export default function Term({ children, explain }: { children: string; explain?: ReactNode }) {
  const [open, setOpen] = useState(false);
  const id = useId();
  const text = explain ?? TERMS[children];
  if (!text) return <>{children}</>;
  return (
    <span className="relative inline-flex items-center gap-1">
      {children}
      <button type="button" aria-label={`What is "${children}"?`} aria-expanded={open} aria-controls={id}
        onClick={() => setOpen((o) => !o)} onBlur={() => setOpen(false)}
        className="inline-flex rounded-full text-current opacity-60 hover:opacity-100 focus-visible:opacity-100">
        <CircleHelp size={13} aria-hidden />
      </button>
      <span id={id} role="note" hidden={!open}
        className="absolute left-0 top-full z-30 mt-1 w-64 rounded-lg border border-line bg-surface p-2.5 text-xs font-normal normal-case leading-5 tracking-normal text-ink shadow-lg">
        {text}
      </span>
    </span>
  );
}
