import { describe, expect, it } from "vitest";
import { asStill, unsaidNumbers } from "./animations";

describe("animated scenes", () => {
  it("turn into the matching still picture with the same words and numbers", () => {
    expect(asStill({ type: "animated", animation: "budget_jars", headline: "Paycheck", items: ["Needs|$1,500", "Wants|$900", "broken"] }))
      .toEqual({ type: "list", headline: "Paycheck", items: ["Needs: $1,500", "Wants: $900"] });
    expect(asStill({ type: "animated", animation: "price_basket", items: ["Eggs|$3.20|$4.10"] }).items).toEqual(["Eggs|$3.20 → $4.10"]);
    expect(asStill({ type: "animated", animation: "counter", stat_value: "53%" }).type).toBe("stat");
    expect(asStill({ type: "animated", animation: "agent_handoff", items: ["A", "B"] }).type).toBe("steps");
  });
  it("flag numbers the narrator doesn't say", () => {
    const scene = { narration: "Eggs went from $3.20 to $4.10.", visual: { type: "animated", animation: "price_basket", items: ["Eggs|$3.20|$4.10", "Milk|$3.90|$4.20"] } };
    expect(unsaidNumbers(scene as any).sort()).toEqual(["3.9", "4.2"]);
    expect(unsaidNumbers({ narration: "x", visual: { type: "stat", stat_value: "99" } } as any)).toEqual([]);
  });
});
