import {describe, expect, it} from "vitest";
import {jobDestination, buildTimeline, type JobRow} from "./activity";
const row = (patch: Partial<JobRow> = {}): JobRow => ({id:"job-1",job_type:"check_providers",status:"running",progress:null,input:{},error_message:null,requested_by:"owner",created_at:"2026-10-26T00:00:00Z",started_at:null,finished_at:null,updated_at:"2026-10-26T00:00:00Z",...patch});
describe("useful destinations",()=>{
  it("opens provider results and selected-idea progress without actions",()=>{
    expect(jobDestination(row())).toBe("/settings/ai?job=job-1#key-check");
    const url = jobDestination(row({job_type:"produce_idea", input:{generated_idea_id:"g1",channel:"ai"}}));
    expect(url).toContain("step=progress"); expect(url).toContain("id=g1");
  });
  it("opens a project or a specific request instead of a generic Activity page",()=>{
    expect(jobDestination(row({job_type:"rerender_preview",project_id:"p1"}))).toBe("/content/p1");
    expect(jobDestination(row({job_type:"run_research"}))).toBe("/activity?job=job-1#job-detail");
  });
  it("retains cancelled requests and links failure history to the exact work",()=>{
    const list=buildTimeline([row({status:"cancelled"}),row({id:"failed",status:"failed",job_type:"run_research",error_message:"No sources"})],[],[]);
    expect(list).toHaveLength(2);expect(list[0].title).toContain("cancelled");expect(list[1].link).toContain("job=failed");
  });
});
