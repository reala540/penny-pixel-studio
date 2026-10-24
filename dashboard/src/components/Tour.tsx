import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { useSaveSetting, useSetting } from "../lib/api";

const STEPS: [string, string][] = [
  ["Welcome to your studio", "It finds ideas, researches them, makes the videos, checks every fact, and posts on your schedule. Five places do everything: Home, Create, Content, Calendar and Activity. Replay this tour from Help."],
  ["Home", "Your starting point: what needs you, what's being made, the next posts and this week's summary. The Create content button starts something new."],
  ["Create", "Step by step: choose a channel, choose or generate an idea, check its sources, create the package and watch it being made."],
  ["Content", "Every package with its video, script, sources, thumbnails, Shorts and posts. Approve it here, unless Auto Review & Post is on. The menu always shows who approves."],
  ["Calendar and Activity", "Calendar shows when posts go out. Activity shows what's running, Quick actions, and every problem with a button to the fix. Settings and Help are at the bottom of the menu."],
];

export const replayTour = () => window.dispatchEvent(new Event("studio-tour"));

/** Five short cards the first time someone signs in. */
export default function Tour() {
  const done = useSetting<boolean>("tour_done", false);
  const save = useSaveSetting();
  const [open, setOpen] = useState(false);
  const [i, setI] = useState(0);
  useEffect(() => {
    if (!done.isLoading && done.data !== true) setOpen(true);
  }, [done.isLoading, done.data]);
  useEffect(() => {
    const replay = () => { setI(0); setOpen(true); };
    window.addEventListener("studio-tour", replay);
    return () => window.removeEventListener("studio-tour", replay);
  }, []);
  if (!open) return null;
  const finish = () => { setOpen(false); if (done.data !== true) save.mutate({ key: "tour_done", value: true }); };
  const [title, body] = STEPS[i];
  return createPortal(
    <div className="fixed inset-0 z-40 flex items-end justify-center bg-ink/40 p-4 sm:items-center">
      <div role="dialog" aria-modal="true" aria-labelledby="tour-title" aria-describedby="tour-body" className="w-full max-w-md rounded-xl bg-surface p-5 shadow-xl"
        onKeyDown={(e) => e.key === "Escape" && finish()}>
        <p className="text-xs text-muted">Step {i + 1} of {STEPS.length}</p>
        <h2 id="tour-title" className="mt-1 font-display text-lg font-semibold">{title}</h2>
        <p id="tour-body" className="mt-2 text-sm text-muted">{body}</p>
        <div className="mt-5 flex items-center justify-between gap-2">
          <button className="btn-quiet" onClick={finish}>Skip tour</button>
          <div className="flex gap-2">
            {i > 0 && <button className="btn-quiet" onClick={() => setI(i - 1)}>Back</button>}
            <button className="btn-primary" autoFocus onClick={() => (i < STEPS.length - 1 ? setI(i + 1) : finish())}>{i < STEPS.length - 1 ? "Next" : "Done"}</button>
          </div>
        </div>
      </div>
    </div>,
    document.body,
  );
}
