import { describe, expect, it } from "vitest";
import { draftSaveLabel } from "./DraftSync";

describe("where a draft is saved, in plain words", () => {
  it("never says 'saved to your account' unless the cloud copy matches", () => {
    expect(draftSaveLabel("ok", true, false)).toBe("Saved to your account");
    expect(draftSaveLabel("ok", false, false)).toBe("Saved on this device · syncing to your account");
    expect(draftSaveLabel("ok", false, true)).toBe("Saved on this device · sync unavailable right now");
    expect(draftSaveLabel("needs_update", true, false)).toContain("sync unavailable until the latest database update");
  });
});
