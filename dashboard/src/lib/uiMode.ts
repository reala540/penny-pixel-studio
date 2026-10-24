// Simple shows the pages most people need; Advanced shows everything. Saved in settings.ui_mode so it's the same
// on every device. New studios start in Simple.
import { useSaveSetting, useSetting } from "./api";

export type UiMode = "simple" | "advanced";

export const SIMPLE_PATHS = new Set(["/week", "/activity", "/review", "/calendar", "/ideas", "/setup", "/settings", "/help"]);

export function useUiMode(): { mode: UiMode; loading: boolean; setMode: (m: UiMode) => Promise<void> } {
  const q = useSetting<UiMode>("ui_mode", "simple");
  const save = useSaveSetting();
  return {
    mode: q.data === "advanced" ? "advanced" : "simple",
    loading: q.isLoading,
    setMode: async (m) => { await save.mutateAsync({ key: "ui_mode", value: m }); },
  };
}
