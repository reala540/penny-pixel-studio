import { supabase } from "./supabase";
// "Clear" for history lists. Clearing hides what's already there from that list (from now on, on every device);
// nothing the studio needs is deleted, so Undo can always bring it back. Stored in settings.ui_cleared.
import { useQueryClient } from "@tanstack/react-query";
import { patchSetting, useSetting } from "./api";

export const CLEAR_KEYS = [
  "activity", "missions", "idea_panel", "idea_runs", "review_log", "rundown_problems",
  "research", "library", "api_errors", "api_stats", "reviewed",
] as const;
export type ClearKey = (typeof CLEAR_KEYS)[number];
export type ClearedMap = Partial<Record<ClearKey, string>>;

/** True when an item made at `iso` was cleared from the list `key`. */
export function isCleared(map: ClearedMap | undefined, key: ClearKey, iso: string | null | undefined): boolean {
  const at = map?.[key];
  return Boolean(at && iso && Date.parse(iso) <= Date.parse(at));
}

export function visibleAfterClear<T>(items: T[], map: ClearedMap | undefined, key: ClearKey, when: (t: T) => string | null | undefined): T[] {
  return items.filter((i) => !isCleared(map, key, when(i)));
}

export function useCleared() {
  const q = useSetting<ClearedMap>("ui_cleared", {});

  const qc = useQueryClient();
  const map = q.data ?? {};
  async function patch(key: ClearKey, value: string | null, expected?: string) {
    const next = await patchSetting("ui_cleared", { [key]: value }, expected ? { [key]: expected } : undefined) as ClearedMap;
    qc.setQueryData(["setting", "ui_cleared"], next);
  }
  return {
    map, since: (key: ClearKey) => map[key],
    clear: async (key: ClearKey): Promise<() => Promise<void>> => {
      const before = map[key] ?? null;
      const stamp = new Date().toISOString();
      await patch(key, stamp);
      return () => patch(key, before, stamp);
    },
  };
}
