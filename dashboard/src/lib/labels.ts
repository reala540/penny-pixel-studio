// Plain words for the studio's technical terms, used by <Term> (a small "?" with a one-sentence explanation).
export const TERMS: Record<string, string> = {
  "What the AI did": "Every request the studio sent to an AI service: which one answered, for which job, and whether it worked.",
  "Jobs in progress": "Work the studio is doing or about to do, such as research, writing a script or rendering a video.",
  "Who's working": "Which AI service is handling each step right now.",
  "Quick actions": "Start a step yourself instead of waiting for the weekly schedule.",
  "Ready to run": "What's connected and working. Anything not ready says what to do.",
  "Quota group": "Keys that share one allowance at the provider. When one is out of free requests, so are the others in its group.",
  "Key rotation": "How the studio takes turns between your keys for the same AI service.",
  "Fact check": "Each fact in a script is checked against the source it came from. Unsupported facts block publishing.",
  "Freshness": "How long the facts in a video stay current. Posts with out-of-date facts are held back.",
  "Auto-fix": "When an automatic check fails, the studio repairs that part and checks everything again, up to the number of attempts you allow.",
  "Trend evidence": "Real, dated sources that show a topic is current. It makes up 70% of an idea's score.",
  "Webhook": "The private link Telegram uses to pass your messages to the studio.",
  "Redirect URL": "Where a platform sends you back after you sign in. It must match exactly in the platform's developer settings.",
};

/** Next step for a problem, by matching the error text. Every error on the Activity page gets a button. */
export function fixFor(text: string | null | undefined): { label: string; to: string } | null {
  const t = (text ?? "").toLowerCase();
  if (!t) return null;
  if (/fresh|content expired|expired facts|stale|recheck/.test(t)) return { label: "Re-check the facts", to: "/calendar" };
  if (/reconnect|expired|needs_reauth|invalid_grant|token .*(expired|revoked)|login/.test(t)) return { label: "Reconnect the account", to: "/settings#accounts" };
  if (/telegram/.test(t)) return { label: "Fix Telegram", to: "/setup#telegram" };
  if (/api key|no key|unauthori[sz]ed|401|403|invalid key|no ai provider|quota|rate limit|429/.test(t)) return { label: "Check AI keys", to: "/api" };
  if (/review|approval|needs your/.test(t)) return { label: "Open Review", to: "/review" };
  if (/post|publish|upload/.test(t)) return { label: "Open Calendar", to: "/calendar" };
  if (/worker|dispatch|github/.test(t)) return { label: "Run the setup check", to: "/setup" };
  return { label: "See what to do", to: "/help" };
}
