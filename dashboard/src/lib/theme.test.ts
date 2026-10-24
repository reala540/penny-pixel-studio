import { describe, expect, it } from "vitest";
import { applyTheme } from "./theme";

describe("theme", () => {
  it("sets an explicit theme and clears it for System", () => {
    const root = { dataset: {} as Record<string, string> } as unknown as HTMLElement;
    applyTheme("dark", root);
    expect(root.dataset.theme).toBe("dark");
    applyTheme("light", root);
    expect(root.dataset.theme).toBe("light");
    applyTheme("system", root);
    expect(root.dataset.theme).toBeUndefined();
  });
});
