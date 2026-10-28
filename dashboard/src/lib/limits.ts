// Each platform's text limits, the same rules the engine checks before approval (engine/studio/publish/limits.py).
const URL_RE = /https?:\/\/|www\.|\b[\w-]+\.(com|net|org|io|co|ai|ke)\b/i;

interface Rule { title?: number; body?: number; caption?: number; tagsTotal?: number; hashtags?: number; noLinks?: boolean }

export const LIMITS: Record<string, Rule> = {
  "youtube:long_video": { title: 100, body: 5000, tagsTotal: 500, hashtags: 15 },
  "youtube:short_video": { title: 100, body: 5000, tagsTotal: 500, hashtags: 15 },
  "x:text_post": { body: 280, noLinks: true },
  "facebook:text_post": { body: 63206 },
  "facebook:reel": { caption: 2200, hashtags: 5 },
  "facebook:long_video": { title: 255, body: 5000 },
  "facebook:story": {},
  "tiktok:short_video": { caption: 2200, hashtags: 5 },
};

export const rule = (platform: string, kind: string): Rule => LIMITS[`${platform}:${kind}`] ?? {};

export function caption(body: string, hashtags: string[]): string {
  return `${body} ${hashtags.filter(Boolean).map((h) => `#${h.replace(/^#/, "")}`).join(" ")}`.trim();
}

/** "a, b, c" → ["a", "b", "c"]; "#x #y" → ["x", "y"]. */
export const parseTags = (s: string) => s.split(",").map((t) => t.trim()).filter(Boolean);
export const parseHashtags = (s: string) => s.split(/[\s,]+/).map((t) => t.replace(/^#+/, "").trim()).filter(Boolean);

export function limitProblems(platform: string, kind: string, p: { title: string; body: string; tags: string[]; hashtags: string[] }): string[] {
  const r = rule(platform, kind);
  const out: string[] = [];
  if (r.title && p.title.length > r.title) out.push(`Title is ${p.title.length} characters (limit ${r.title})`);
  if (r.body && p.body.length > r.body) out.push(`Text is ${p.body.length} characters (limit ${r.body})`);
  if (r.caption) { const n = caption(p.body, p.hashtags).length; if (n > r.caption) out.push(`Caption with hashtags is ${n} characters (limit ${r.caption})`); }
  if (r.tagsTotal) { const n = p.tags.reduce((a, t) => a + t.length, 0) + Math.max(p.tags.length - 1, 0); if (n > r.tagsTotal) out.push(`Tags add up to ${n} characters (limit ${r.tagsTotal})`); }
  if (r.hashtags && p.hashtags.length > r.hashtags) out.push(`${p.hashtags.length} hashtags (at most ${r.hashtags})`);
  if (r.noLinks && URL_RE.test(p.body)) out.push("Contains a link (links are blocked on X to protect the budget)");
  if (kind === "text_post" && !p.body.trim()) out.push("The post text is empty");
  return out;
}
