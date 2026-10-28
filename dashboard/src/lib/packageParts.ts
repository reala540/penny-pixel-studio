// What a package is made of, said plainly: the main video, its short videos, and the posts on each platform.
import type { Claim, Project } from "./types";

export interface DroppedShort { title: string; reasons: string[] }

/** Shorts the quality checks rejected, from the saved package notes ("Short 'X' dropped: ['a', 'b']"). */
export function droppedShorts(qr: Project["quality_report"]): DroppedShort[] {
  const lines: string[] = [...(qr?.package_problems ?? []), ...((qr?.shorts_remakes ?? []) as { problems?: string[] }[]).flatMap((r) => r.problems ?? [])];
  const out: DroppedShort[] = [];
  for (const line of lines) {
    const m = /Short '(.+?)' dropped: \[(.*)\]\s*$/.exec(String(line));
    if (!m) continue;
    const reasons = [...m[2].matchAll(/'((?:[^'\\]|\\.)*)'|"((?:[^"\\]|\\.)*)"/g)].map((x) => x[1] ?? x[2]);
    out.push({ title: m[1], reasons: reasons.length ? reasons : [m[2]] });
  }
  return out;
}

const SHORTS_LINE = /^(Retry \d+: )?Short '.+' dropped:/;

/** Warnings worth showing for this package. The script's length estimate is replaced by the video's real length,
 *  and the per-Short drop lines are shown in Short videos instead. */
export function visibleIssues(project: Pick<Project, "quality_report" | "recipe" | "format">): string[] {
  const qr = project.quality_report ?? {};
  const seconds = Number(project.recipe?.preview_seconds) || 0;
  const issues = [...(qr.issues ?? []), ...(qr.package_problems ?? [])].filter((i: string) => !SHORTS_LINE.test(i));
  if (project.format === "long" && seconds >= 480) return issues.filter((i: string) => !/^Too short: about /.test(i));
  return issues;
}

export function claimProblems(claims: Pick<Claim, "status">[]) {
  return {
    contradicted: claims.filter((c) => c.status === "contradicted").length,
    unsupported: claims.filter((c) => c.status === "unsupported").length,
  };
}

export const SHORTS_WAITING = ["ready_for_review", "needs_attention"];
