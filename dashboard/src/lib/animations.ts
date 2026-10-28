// The original animated scenes the renderer can draw (engine/studio/media/animate.py), and how each one is filled in.
import type { Scene } from "./types";

export const ANIMATIONS = [
  { id: "budget_jars", label: "Coins into budget jars", help: "One line per jar: Label|amount, e.g. Rent|$1,200 (2-4 jars)", still: "list" },
  { id: "price_basket", label: "Shopping basket, prices rising", help: "One line per item: Item|before|after, e.g. Eggs|$3.20|$4.10 (1-4 items)", still: "comparison" },
  { id: "agent_handoff", label: "AI agents passing a task", help: "One line per step, e.g. Research (2-5 steps)", still: "steps" },
  { id: "counter", label: "A number counting up", help: "Uses the number and label below", still: "stat" },
] as const;

export type AnimationId = (typeof ANIMATIONS)[number]["id"];

/** The still version of an animated scene: same words and numbers, no movement. */
export function asStill(v: Scene["visual"]): Scene["visual"] {
  const a = ANIMATIONS.find((x) => x.id === v.animation);
  const items = v.items ?? [];
  const rows = (n: number) => items.map((i) => i.split("|").map((c) => c.trim())).filter((r) => r.length >= n && r.slice(0, n).every(Boolean));
  const { animation: _drop, ...rest } = v;
  if (v.animation === "budget_jars") return { ...rest, type: "list", items: rows(2).map((r) => `${r[0]}: ${r[1]}`) };
  if (v.animation === "price_basket") return { ...rest, type: "comparison", items: rows(3).map((r) => `${r[0]}|${r[1]} → ${r[2]}`) };
  return { ...rest, type: a?.still ?? "title_card" };
}

/** Numbers an animation shows that its narration doesn't say (the engine flags these too). */
export function unsaidNumbers(scene: Scene): string[] {
  if (scene.visual.type !== "animated") return [];
  const nums = (t: string) => new Set([...t.matchAll(/(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)/g)].map((m) => {
    let n = m[1].replace(/,/g, ""); if (n.includes(".")) n = n.replace(/0+$/, "").replace(/\.$/, ""); return n; }));
  const said = nums(scene.narration);
  return [...nums([...(scene.visual.items ?? []), scene.visual.stat_value ?? ""].join(" "))].filter((n) => !said.has(n));
}
