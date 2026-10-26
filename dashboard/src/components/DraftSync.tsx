// Local-first recovery: device copies survive outages; cloud revisions prevent silent overwrites.
import { useEffect, useState, useSyncExternalStore } from "react";
import { cleanDraft, listDrafts, mergeCloudDrafts, newDraftId, useOwnerId, type CreateDraft } from "../lib/drafts";
import { supabase } from "../lib/supabase";

type CloudRow = {id: string; payload: CreateDraft | null; revision: number};

// "needs_update": the database doesn't have cloud drafts yet (migration 13). Drafts still work on this device;
// that's said once where drafts are listed, not as a page-wide error with a Retry that can't help.
let cloud: "unknown" | "ok" | "needs_update" = "unknown";
const listeners = new Set<() => void>();
const setCloud = (v: typeof cloud) => { if (cloud !== v) { cloud = v; listeners.forEach((l) => l()); } };
export const useCloudDrafts = () => useSyncExternalStore((cb) => { listeners.add(cb); return () => listeners.delete(cb); }, () => cloud, () => cloud);
const notInstalled = (e: { code?: string; message?: string } | null) =>
  ["PGRST202", "PGRST205", "42P01", "42883"].includes(e?.code ?? "") || /schema cache/i.test(e?.message ?? "");
export default function DraftSync() {
  const owner = useOwnerId();
  const [message, setMessage] = useState("");
  useEffect(() => {
    if (!owner) return;
    let live = true, busy = false;
    let timer = 0;
    const metaKey = `studio-draft-cloud:${owner}`;
    const same = (a: unknown,b: unknown) => JSON.stringify(a)===JSON.stringify(b);
    const sync = async () => {
      if (busy || navigator.onLine === false) return;
      busy = true;
      try {
        const response = await supabase.from("studio_drafts").select("id,payload,revision").eq("owner_id",owner).order("updated_at", {ascending:false}).limit(200);
        if (notInstalled(response.error)) { setCloud("needs_update"); clearInterval(timer); if (live) setMessage(""); return; }
        if (response.error) throw new Error("Drafts are kept on this device; the cloud copy couldn't be updated just now.");
        setCloud("ok");
        if (!live) return;
        let meta: Record<string,{revision:number;payload:CreateDraft|null}> = {};
        try {meta=JSON.parse(localStorage.getItem(metaKey)??"{}");} catch { /* first use */ }
        let local = listDrafts(owner);
        let recovered = false;
        const removedKey=`studio-draft-removed:${owner}`;
        let pendingRemovals: string[]=JSON.parse(localStorage.getItem(removedKey)??"[]");
        const remote = response.data as CloudRow[];
        for (const row of remote) {
          const here = local.find(d=>d.id===row.id);
          const before = meta[row.id];
          if (before?.revision===row.revision) continue;
          if (before && pendingRemovals.includes(row.id)) {
            // Another device edited the bookmark after this device removed it. Restore it for review.
            pendingRemovals=pendingRemovals.filter(id=>id!==row.id);
            localStorage.setItem(removedKey,JSON.stringify(pendingRemovals));
            recovered=true;
          }
          if (here && !same(here,before?.payload) && !same(here,row.payload)) {
            // Concurrent edits are both preserved; never let background syncing pick a winner.
            local=local.filter(d=>d.id!==row.id);
            local.push(cleanDraft({...here,id:newDraftId(),ideaTitle:`${here.ideaTitle??"Your idea"} (recovered copy)`}));
            recovered=true;
          } else local=local.filter(d=>d.id!==row.id);
          if (row.payload) local.push(cleanDraft(row.payload));
          meta[row.id]={revision:row.revision,payload:row.payload};
        }
        mergeCloudDrafts(owner,local);
        // Re-read in case a local edit happened while the network request was pending.
        local=listDrafts(owner);
        for (const d of local) {
          const before=meta[d.id];
          if (same(d,before?.payload)) continue;
          const result=await supabase.rpc("save_studio_draft",{p_id:d.id,p_payload:cleanDraft(d),p_expected:before?.revision??0});
          if (notInstalled(result.error)) { setCloud("needs_update"); clearInterval(timer); if (live) setMessage(""); return; }
          if (result.error || !result.data?.revision || result.data?.conflict) throw new Error("Drafts are saved on this device; cloud sync needs Retry. Both devices' versions are preserved.");
          meta[d.id]={revision:result.data.revision,payload:d};
          localStorage.setItem(metaKey,JSON.stringify(meta));
        }
        // Only explicitly removed drafts get tombstones; expiry/limits never delete cloud data.
        const removed: string[]=JSON.parse(localStorage.getItem(removedKey)??"[]");
        for(const id of removed) {
          if(!meta[id]) continue;
          const result=await supabase.rpc("save_studio_draft",{p_id:id,p_payload:null,p_expected:meta[id].revision});
          if(result.error || result.data?.conflict) throw new Error("A removed draft changed on another device. Refresh to review it before removing again.");
          meta[id]={revision:result.data.revision,payload:null};
        }
        localStorage.setItem(removedKey,"[]");
        localStorage.setItem(metaKey,JSON.stringify(meta));
        if(live)setMessage(recovered ? "Drafts changed on another device. Both versions were kept; review your recovered copy in Create." : "");
      } catch(e) {if(live)setMessage((e as Error).message);}
      finally {busy=false;}
    };
    void sync();
    timer=window.setInterval(sync,15000);
    window.addEventListener("online",sync);
    return()=>{live=false;clearInterval(timer);window.removeEventListener("online",sync);};
  },[owner]);
  return message ? <div role="status" className="border-b border-line bg-gold/10 px-4 py-2 text-sm">{message} <button className="underline" onClick={()=>window.dispatchEvent(new Event("online"))}>Retry sync</button></div>:null;
}
