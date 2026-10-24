import { describe, expect, it } from "vitest";
import { legacyRedirect } from "./routes";

describe("old addresses", () => {
  it("send Telegram and bookmark links to the new pages", () => {
    expect(legacyRedirect("/review/abc-123")).toBe("/content/abc-123");
    expect(legacyRedirect("/review")).toBe("/content?tab=needs-you");
    expect(legacyRedirect("/week")).toBe("/");
    expect(legacyRedirect("/library")).toBe("/content?tab=all");
    expect(legacyRedirect("/ideas")).toBe("/content/ideas");
    expect(legacyRedirect("/research")).toBe("/content/ideas?source=research");
    expect(legacyRedirect("/mission")).toBe("/activity");
    expect(legacyRedirect("/api")).toBe("/settings/ai");
    expect(legacyRedirect("/setup", "", "#telegram")).toBe("/settings/setup#telegram");
  });

  it("keep platform sign-in returns and their messages", () => {
    expect(legacyRedirect("/settings", "?connected=youtube")).toBe("/settings/accounts?connected=youtube");
    expect(legacyRedirect("/settings", "?connect_error=Access%20denied")).toBe("/settings/accounts?connect_error=Access%20denied");
  });

  it("map the old Settings anchors to sections", () => {
    expect(legacyRedirect("/settings", "", "#automation")).toBe("/settings/automation");
    expect(legacyRedirect("/settings", "", "#posting-schedule")).toBe("/settings/schedule");
    expect(legacyRedirect("/settings", "", "#accounts")).toBe("/settings/accounts");
    expect(legacyRedirect("/settings", "", "#run")).toBe("/activity#quick-actions");
    expect(legacyRedirect("/settings", "", "#telegram")).toBe("/settings/notifications");
    expect(legacyRedirect("/settings")).toBe("/settings/setup");
  });

  it("leave current addresses alone", () => {
    for (const p of ["/", "/create", "/content", "/content/x", "/calendar", "/activity", "/settings/ai", "/help"]) {
      expect(legacyRedirect(p)).toBeNull();
    }
  });
});
