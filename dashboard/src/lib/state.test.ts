import { describe, expect, it } from "vitest";
import { friendlyError, isConfirmed, known, safePath } from "./state";

const q = (over: Partial<Parameters<typeof known>[0]>) =>
  ({ isLoading: false, isError: false, error: null, data: undefined, isSuccess: false, dataUpdatedAt: 0, ...over });

describe("known(): a failed or unfinished request is never an answer", () => {
  it("loading is loading, not OFF", () => {
    expect(known(q({ isLoading: true }))).toEqual({ state: "loading" });
  });

  it("a failure is failed, not the fallback value", () => {
    const k = known(q({ isError: true, error: new Error("Failed to fetch") }));
    expect(k.state).toBe("failed");
    expect(isConfirmed(k)).toBe(false);
    if (k.state === "failed") expect(k.error).toContain("Couldn't reach the studio");
  });

  it("keeps the last confirmed value next to a failure, marked as last known", () => {
    const k = known(q({ isError: true, error: new Error("boom"), data: true, dataUpdatedAt: 1 }));
    expect(k).toMatchObject({ state: "failed", last: true });
  });

  it("offline is offline, with or without a last value", () => {
    expect(known(q({ isError: true, error: new Error("x") }), false).state).toBe("offline");
    expect(known(q({ isLoading: true }), false).state).toBe("offline");
  });

  it("only a successful answer is confirmed, including a confirmed false", () => {
    expect(known(q({ isSuccess: true, data: false, dataUpdatedAt: 1 }))).toEqual({ state: "confirmed", value: false });
  });
});

describe("friendlyError", () => {
  it.each([
    ["TypeError: Failed to fetch", "Couldn't reach the studio"],
    ["JWT expired", "sign-in has expired"],
    ['new row violates row-level security policy for table "settings"', "only the studio owner"],
    ['duplicate key value violates unique constraint "x"', "already exists"],
    ["The operation timed out", "took too long"],
  ])("%s", (raw, expected) => {
    expect(friendlyError(new Error(raw))).toContain(expected);
  });

  it("passes other messages through, shortened", () => {
    expect(friendlyError(new Error("Choose an idea first."))).toBe("Choose an idea first.");
    expect(friendlyError("x".repeat(400)).length).toBeLessThanOrEqual(301);
    expect(friendlyError(undefined)).toBe("Something went wrong. Try again.");
  });
});

describe("safePath: only this site's pages after sign-in", () => {
  it("accepts in-app paths with query and anchor", () => {
    expect(safePath("/content/abc?tab=posts#v1")).toBe("/content/abc?tab=posts#v1");
  });
  it.each(["https://evil.test/", "//evil.test", "/\\evil.test", "javascript:alert(1)", "", null])("rejects %s", (p) => {
    expect(safePath(p as string | null)).toBeNull();
  });
});
