import { describe, expect, it } from "vitest";
import { accountChange } from "./AuthGate";

describe("switching accounts never shows the previous account's data", () => {
  it("clears the cache for another account or a sign-out, keeps it for a token refresh", () => {
    expect(accountChange(null, "owner", "SIGNED_IN")).toEqual({ clear: false, user: "owner" });
    expect(accountChange("owner", "owner", "TOKEN_REFRESHED")).toEqual({ clear: false, user: "owner" });
    expect(accountChange("owner", "someone-else", "SIGNED_IN")).toEqual({ clear: true, user: "someone-else" });
    expect(accountChange("owner", null, "SIGNED_OUT")).toEqual({ clear: true, user: null });
    expect(accountChange(null, null, "SIGNED_OUT")).toEqual({ clear: true, user: null });
  });
});
