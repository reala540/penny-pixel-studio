import { useSyncExternalStore } from "react";

export type ThemePref = "light" | "dark" | "system";

// Kept in this browser only (a per-device preference). index.html applies it before the first paint.
export const THEME_KEY = "studio-theme";
const EVENT = "studio-theme-change";

export function readTheme(): ThemePref {
  try {
    const v = localStorage.getItem(THEME_KEY);
    return v === "light" || v === "dark" ? v : "system";
  } catch {
    return "system";
  }
}

export function applyTheme(pref: ThemePref, root: HTMLElement = document.documentElement): void {
  // "system" removes the override so the CSS follows prefers-color-scheme, live.
  if (pref === "system") delete root.dataset.theme;
  else root.dataset.theme = pref;
}

export function setTheme(pref: ThemePref): void {
  try {
    if (pref === "system") localStorage.removeItem(THEME_KEY);
    else localStorage.setItem(THEME_KEY, pref);
  } catch {
    // storage blocked (private mode): the choice still applies until the tab closes
  }
  applyTheme(pref);
  window.dispatchEvent(new Event(EVENT));
}

function subscribe(cb: () => void): () => void {
  const onStorage = (e: StorageEvent) => {
    if (e.key === THEME_KEY) {
      applyTheme(readTheme());  // another tab changed it
      cb();
    }
  };
  window.addEventListener(EVENT, cb);
  window.addEventListener("storage", onStorage);
  return () => {
    window.removeEventListener(EVENT, cb);
    window.removeEventListener("storage", onStorage);
  };
}

export function useTheme(): [ThemePref, (p: ThemePref) => void] {
  return [useSyncExternalStore(subscribe, readTheme, () => "system" as ThemePref), setTheme];
}
