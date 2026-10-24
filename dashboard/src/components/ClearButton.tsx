import { Eraser } from "lucide-react";
import { ReactNode, useState } from "react";
import { Confirm, useToast } from "./ui";

type Undo = () => Promise<void> | void;

/** A Clear button that always asks first and, where possible, offers Undo for a few seconds afterwards. */
export default function ClearButton({ label = "Clear", title, body, done = "Cleared", onClear, disabled, danger, className = "btn-quiet" }: {
  label?: string; title: string; body: ReactNode; done?: string; disabled?: boolean; danger?: boolean; className?: string;
  onClear: () => Promise<Undo | void>;
}) {
  const [ask, setAsk] = useState(false);
  const [busy, setBusy] = useState(false);
  const toast = useToast();
  return (
    <>
      <button type="button" className={className} disabled={disabled || busy} onClick={() => setAsk(true)}>
        <Eraser size={14} aria-hidden />{label}
      </button>
      <Confirm open={ask} title={title} body={body} confirmLabel={label} danger={danger}
        onCancel={() => setAsk(false)}
        onConfirm={async () => {
          setAsk(false);
          setBusy(true);
          try {
            const undo = await onClear();
            toast(done, "good", undo ? { label: "Undo", run: async () => { await undo(); toast("Restored"); } } : undefined);
          } catch (e) {
            toast((e as Error).message, "bad");
          } finally {
            setBusy(false);
          }
        }} />
    </>
  );
}
