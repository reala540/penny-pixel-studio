import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { useSaveSetting, useSetting } from "../lib/api";

const STEPS: [string, string][] = [
  ["Welcome to your studio", "It finds ideas, researches them, writes and makes the videos, checks every fact, and posts on your schedule. This short tour shows where things are. You can replay it from Help."],
  ["This Week", "What's going out this week on each account, what's waiting for you, and the pause button that stops all posting at once."],
  ["Review", "Watch each video, check its sources, tweak the words, then approve. Nothing posts until it's approved, by you or (if you switch it on) by Auto Review & Post."],
  ["Activity", "What the studio is doing right now and everything it has done. Any problem has a button that takes you straight to the fix."],
  ["Setup and Settings", "Setup walks you through every connection with a ✅ for each step. Settings holds your schedule and house rules. The menu switch at the bottom shows Simple or Advanced pages."],
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
