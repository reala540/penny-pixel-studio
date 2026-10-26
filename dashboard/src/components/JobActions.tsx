import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";
import { jobDestination, type JobRow } from "../lib/activity";
import { must } from "../lib/api";
import { supabase } from "../lib/supabase";
import { Confirm, useToast } from "./ui";

/** View/continue the request and (while it runs) cancel only this request. `here`: already on its progress page. */
export default function JobActions({ job, here = false }: { job: JobRow; here?: boolean }) {
  const [ask, setAsk] = useState(false);
  const [stopping, setStopping] = useState(false);
  const toast = useToast();
  const qc = useQueryClient();
  const cancel = useMutation({
    mutationFn: () => must(supabase.rpc("cancel_owner_job", { p_job_id: job.id })),
    onSuccess: (state) => { setStopping(state === "stopping"); toast(state === "stopping" ? "Stop requested. The current external request may finish before this job stops." : "Job cancelled; saved work is kept."); qc.invalidateQueries(); },
    onError: (e) => toast(/function|schema cache/i.test((e as Error).message) ? "This installation needs an update before individual jobs can be cancelled. No work was stopped." : (e as Error).message, "bad"),
  });
  const active = ["queued", "running", "retrying"].includes(job.status);
  return <div className="mt-2 flex flex-wrap items-center gap-3 text-sm">
    {!here && <Link className="text-pixel underline" to={jobDestination(job)}>{active ? "View progress" : job.status === "cancelled" ? "Continue" : ["failed","blocked","needs_review"].includes(job.status) ? "Fix problem" : "View results"}</Link>}
    {active && job.requested_by === "owner" && <button className="btn-quiet" disabled={cancel.isPending || (Boolean(job.cancel_requested_at) || stopping)} onClick={() => setAsk(true)}>{job.cancel_requested_at || stopping ? "Stopping…" : "Cancel work"}</button>}
    <Confirm open={ask} title="Cancel this job?" body="Only this request will stop at its next checkpoint. Completed work is kept. Other projects, scheduled posts, and publishing are not cancelled. An external request already in progress may finish first." confirmLabel="Cancel work" onCancel={() => setAsk(false)} onConfirm={() => {setAsk(false); cancel.mutate();}} />
  </div>;
}
