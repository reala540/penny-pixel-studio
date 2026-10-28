// Old addresses keep working: Telegram messages, bookmarks and platform sign-in returns still use them.

/** Settings sections, in menu order. */
export const SETTINGS_SECTIONS = [
  ["setup", "Getting started"],
  ["accounts", "Accounts"],
  ["schedule", "Posting schedule"],
  ["automation", "Automation"],
  ["ideas", "Ideas & research"],
  ["ai", "AI services & keys"],
  ["voices", "Channel voices"],
  ["notifications", "Notifications"],
  ["budget", "Budget"],
  ["offers", "Affiliate offers"],
  ["appearance", "Appearance & region"],
] as const;
export type SettingsSection = (typeof SETTINGS_SECTIONS)[number][0];

/** Old one-page Settings anchors → the new section (or another page). */
const SETTINGS_HASH: Record<string, string> = {
  appearance: "/settings/appearance", ideas: "/settings/ideas", automation: "/settings/automation",
  "posting-schedule": "/settings/schedule", providers: "/settings/ai", writers: "/settings/ai", accounts: "/settings/accounts",
  run: "/activity#quick-actions", voices: "/settings/voices", budget: "/settings/budget", schedule: "/settings/appearance",
  telegram: "/settings/notifications",
};

/** Where an old address now lives, or null if it's current. Query strings and anchors are kept. */
export function legacyRedirect(pathname: string, search = "", hash = ""): string | null {
  const keep = (to: string, extraSearch = search) => `${to}${extraSearch}${to.includes("#") ? "" : hash}`;
  const p = pathname.replace(/\/+$/, "") || "/";
  if (p === "/week") return keep("/");
  if (p === "/mission") return keep("/activity");
  if (p === "/review") return keep("/content", mergeSearch(search, "tab=needs-you"));
  const review = p.match(/^\/review\/([^/]+)$/);
  if (review) return keep(`/content/${review[1]}`);
  if (p === "/library") return keep("/content", mergeSearch(search, "tab=all"));
  if (p === "/ideas") return keep("/content/ideas");
  if (p === "/research") return keep("/content/ideas", mergeSearch(search, "source=research"));
  if (p === "/setup") return keep("/settings/setup");
  if (p === "/api") return keep("/settings/ai");
  if (p === "/settings") {
    // OAuth returns arrive as /settings?connected=youtube or ?connect_error=…: show them on Accounts
    if (/[?&](connected|connect_error)=/.test(search)) return `/settings/accounts${search}`;
    const section = SETTINGS_HASH[hash.replace(/^#/, "")];
    if (section) return section.includes("#") ? section : `${section}${search}`;
    return `/settings/setup${search}`;
  }
  return null;
}

function mergeSearch(search: string, add: string): string {
  const params = new URLSearchParams(search);
  const [k, v] = add.split("=");
  if (!params.has(k)) params.set(k, v);
  const s = params.toString();
  return s ? `?${s}` : "";
}

export const projectPath = (id: string, tab?: string) => `/content/${id}${tab ? `?tab=${tab}` : ""}`;
