// Only non-secret editors use this hook; credential/password forms must never import it.
import { useEffect, useRef, useState } from "react";
import { looksLikeSecret, useOwnerId } from "./drafts";

export function useFormDraft<T>(name: string, initial: T) {
  const owner = useOwnerId();
  const key = `studio-form:${owner}:${name}`;
  const initialText = JSON.stringify(initial);
  const recovered = useRef<{base: string; value: T} | null>(null);
  if (recovered.current === null && owner) { try { recovered.current = JSON.parse(localStorage.getItem(key) ?? "null"); } catch { /* unavailable storage */ } }
  const base = useRef(recovered.current?.base ?? initialText);
  const [conflict, setConflict] = useState(Boolean(recovered.current && recovered.current.base !== initialText));
  const [error, setError] = useState("");
  const [value, setValue] = useState<T>(() => {
    try {
      const saved = owner ? JSON.parse(localStorage.getItem(key) ?? "null") : null;
      return saved ? saved.value as T : initial;
    } catch { return initial; }
  });
  const text = JSON.stringify(value);
  const dirty = text !== initialText;
  useEffect(() => {
    if (base.current !== initialText) {
      if (text !== base.current && text !== initialText) { setConflict(true); return; }
      base.current = initialText; setValue(initial); setConflict(false);
    }
  }, [initialText]);
  useEffect(() => {
    if (!owner || conflict) return;
    try {
      if (!dirty) localStorage.removeItem(key);
      else if (looksLikeSecret(text)) { setError("This text looks like a credential; it is not saved as a draft."); return; }
      else localStorage.setItem(key, JSON.stringify({ base: base.current, value }));
      setError("");
    } catch { setError("Couldn't keep a recovery draft on this device. Save before leaving."); }
  }, [key, text, dirty, conflict, owner]);
  useEffect(() => {
    if (!dirty) return;
    const warn = (e: BeforeUnloadEvent) => { e.preventDefault(); e.returnValue = ""; };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);
  const reset = () => { base.current = initialText; setValue(initial); setConflict(false); };
  const message = conflict ? "This changed elsewhere. Your edits are kept; discard them to load the current version before saving." : error || (dirty ? "Unsaved changes. A recovery copy is kept on this device only (not in your account) until you save." : "");
  return [value, setValue, { dirty, conflict, message, reset }] as const;
}
