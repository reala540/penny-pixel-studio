import { describe, expect, it } from "vitest";
import { buildTimeline, inFilter, jobTitle, type JobRow } from "./activity";
import { isCleared, visibleAfterClear } from "./clear";
import { fixFor } from "./labels";

const job = (over: Partial<JobRow>): JobRow => ({
  id: "j", job_type: "generate_ideas", status: "completed", progress: null, input: {}, error_message: null, requested_by: "owner",
  created_at: "2026-10-25T08:00:00Z", started_at: "2026-10-25T08:00:00Z", finished_at: "2026-10-25T08:05:00Z", updated_at: "2026-10-25T08:05:00Z",
  ...over,
});

describe("activity timeline", () => {
  it("merges jobs, notifications and settings changes newest first, in plain words", () => {
    const items = buildTimeline(
      [job({ id: "a" }), job({ id: "b", job_type: "regenerate_script", status: "failed", error_message: "Login expired", finished_at: "2026-10-25T09:00:00Z",
        input: { auto_fix: true }, content_projects: { title: "AI tools" } }), job({ id: "c", job_type: "script", status: "completed" })],
      [{ id: "n", kind: "published", title: "Posted to YouTube", body: null, link: null, created_at: "2026-10-25T10:00:00Z", error: null }],
      [{ id: 1, actor: "owner", action: "auto_review_post_on", details: {}, created_at: "2026-10-25T07:00:00Z" },
        { id: 2, actor: "owner", action: "something_internal", details: {}, created_at: "2026-10-25T07:30:00Z" }],
    );
    expect(items.map((i) => i.title)).toEqual([
      "Posted to YouTube",
      "Rewriting a script: AI tools (automatic fix): failed",
      "Generating ideas: finished",
      "Auto Review & Post switched ON",
    ]);
    expect(items[1]).toMatchObject({ tone: "bad", error: true, category: "production", detail: "Login expired" });
    expect(items.filter((i) => inFilter(i, "errors"))).toHaveLength(1);
    expect(items.filter((i) => inFilter(i, "posting"))).toHaveLength(1);
    expect(jobTitle(job({ job_type: "weekly_research" }))).toBe("Weekly research");
  });

  it("every problem gets a next step", () => {
    expect(fixFor("TikTok login expired, reconnect")).toEqual({ label: "Reconnect the account", to: "/settings/accounts" });
    expect(fixFor("429 rate limit from gemini")?.to).toBe("/settings/ai");
    expect(fixFor("content expired: recheck before publishing")?.label).toBe("Re-check the facts");
    expect(fixFor("something odd")?.to).toBe("/help");
    expect(fixFor("")).toBeNull();
  });

  it("clear hides only what existed when it was pressed", () => {
    const map = { activity: "2026-10-25T09:00:00Z" };
    expect(isCleared(map, "activity", "2026-10-25T08:59:59Z")).toBe(true);
    expect(isCleared(map, "activity", "2026-10-25T09:00:01Z")).toBe(false);
    expect(isCleared(map, "missions", "2026-10-25T08:00:00Z")).toBe(false);
    expect(visibleAfterClear([{ at: "2026-10-25T08:00:00Z" }, { at: "2026-10-25T10:00:00Z" }], map, "activity", (x) => x.at)).toHaveLength(1);
  });
});
