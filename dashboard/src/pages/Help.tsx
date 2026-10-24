import { Link } from "react-router-dom";
import { replayTour } from "../components/Tour";
import { PageHeader } from "../components/ui";

const GUIDE: { title: string; steps: string[] }[] = [
  {
    title: "Getting started (once)",
    steps: [
      "Open Settings → Getting started. Each step tests itself and shows ✅ when it works: the basics and AI keys (needed to create), then YouTube, Facebook, TikTok and X (needed to publish). Telegram alerts are recommended, not required.",
      "Paste values there, not in GitHub. They're encrypted on the server and the page only shows the last 4 characters.",
      "Make your first video: Create → choose a channel → choose or generate an idea → check its sources → Create package. Progress shows on the same page.",
      "Review it in Content when it's ready, then approve. After a week or two of good packages, you can switch on Auto Review & Post.",
    ],
  },
  {
    title: "Your weekly routine",
    steps: [
      "Saturday: the studio researches topics. Sunday: it writes, checks and renders the videos, and Telegram tells you when they're ready.",
      "Monday: open Content → Needs you, watch each package, check its sources, and approve or discard it (or let Auto Review & Post do it).",
      "During the week: approved posts go out on schedule. Home and Calendar show what's planned; Activity shows what happened.",
    ],
  },
  {
    title: "When something goes wrong",
    steps: [
      "Open Activity → Problems. Every problem has a button that takes you to the fix (reconnect an account, check a key, re-check facts…).",
      "To stop all posting at once, press Pause publishing on Home or in Settings → Automation, or send /pause to your Telegram bot. Making content keeps working.",
      "If a setup value stopped working, open Settings → Getting started and press Test next to it. For AI keys, press Test again in Settings → AI services & keys.",
    ],
  },
];

const FAQ: [string, string][] = [
  ["What happens each week?", "Saturday morning the studio collects news and data and picks ideas. Sunday it writes, checks and renders the videos. Sunday evening you get a Telegram message. You review on Monday, and approved posts go out during the week."],
  ["How do I see what's running?", "The line at the bottom of the menu always says what the studio is doing. Open Activity for the full picture: what's running now with its progress, today's numbers, and a timeline of every idea, video, review and post."],
  ["Why does a video say \"Needs a look\"?", "An automatic check found something: a fact without a source, a phrase that sounds generic, or a length problem. Open it in Content; the box beside the video lists exactly what to check."],
  ["What is Auto Review & Post?", "OFF (default): you approve everything. ON: the AI approves only packages that pass every check (quality, sourced facts, freshness, the right accounts, licences, and a confident independent policy review); they post at their normal times. Switch it in Settings → Automation or with /autopost in Telegram. The menu always shows who approves."],
  ["What happens when a check fails with Auto Review & Post ON?", "The studio fixes only the part that failed (the post text, the script, the facts or a photo) and runs every check again, up to 3 times by default (Settings → Automation). If it passes, it posts at the next free slot on that account's schedule. A disconnected account or a policy concern is never retried, and anything still failing comes to you on Telegram."],
  ["What does Clear do?", "Clear hides old items from a list so you can start fresh. It always asks first, and most clears can be undone for a few seconds. Published posts and the audit log can never be cleared."],
  ["Where do I change posting days and times?", "Settings → Posting schedule. Pick days and times for each account, the number of posts per week, or pause an account. The preview shows the week before you save."],
  ["Where did Mission Control, Review, Library and Research go?", "Into the five main pages: making things is in Create, every package (with its video, script, sources and posts) is in Content, ideas from research and the Idea Generator are in Content → Ideas, and monitoring (AI calls, jobs, model council) is in Activity → Technical details. Old links still work."],
  ["Do I still need the GitHub secrets?", "Keep the core ones forever (database, encryption key, Cloudflare, Worker GitHub token, dashboard address); the studio needs them before it can reach its database. Everything else can be saved in Settings → Getting started, which shows \"Also in GitHub: safe to remove there\" once a value is saved in the dashboard."],
  ["What does \"Post it yourself\" mean?", "The platform didn't let the studio post automatically (for example before YouTube or TikTok approve the app). Download the approved file from the package in Content, post it, then press Done on Home."],
  ["Why was a post blocked?", "Usually because the facts in it are older than their freshness date. Use \"Re-check the facts\" in Calendar, or discard the package."],
  ["Will this ever charge me?", "Only X costs money, capped by your monthly limit (at most $1). Every other service is used on its free tier, and when a free allowance runs out the studio waits or uses another free service."],
  ["How are idea scores worked out?", "70 of the 100 points come from real, dated sources the idea cites. The other 30 are an AI reviewer's opinion of originality, international relevance, feasibility and engagement. An idea with no current source is marked Trend unverified."],
  ["Can I add more than one key for an AI service?", "Yes, in Settings → AI services & keys. Each provider shows a label: \"Add more keys\" (Gemini, Cloudflare, Z.ai, Cerebras, SambaNova), \"One key only\" (Groq), \"Borrowed keys not allowed\" (NVIDIA, Mistral) or \"Check the owner's terms\". Keys from the same account share one limit; tick \"separate account\" only for a key with its own allowance."],
  ["How do I switch to dark mode?", "Use the sun / moon / screen buttons at the bottom of the menu, or Settings → Appearance & region."],
];

export default function Help() {
  return (
    <>
      <PageHeader title="Help" intro="How the studio works and what to do. The complete guide is GUIDE.md in your GitHub repository."
        actions={<><Link to="/settings/setup" className="btn-primary">Getting started</Link><button className="btn-quiet" onClick={replayTour}>Replay the tour</button></>} />
      <div className="mb-10 grid max-w-5xl gap-4 lg:grid-cols-3">
        {GUIDE.map((g) => (
          <section key={g.title} aria-labelledby={`g-${g.title}`} className="rounded-xl border border-line bg-surface p-5">
            <h2 id={`g-${g.title}`} className="font-display text-base font-semibold">{g.title}</h2>
            <ol className="mt-3 list-decimal space-y-2 pl-5 text-sm text-muted">{g.steps.map((s) => <li key={s}>{s}</li>)}</ol>
          </section>
        ))}
      </div>
      <h2 className="section-title mb-3">Questions</h2>
      <dl className="max-w-3xl divide-y divide-line rounded-xl border border-line bg-surface">
        {FAQ.map(([q, a]) => (
          <div key={q} className="px-5 py-4">
            <dt className="font-display text-base font-semibold">{q}</dt>
            <dd className="mt-1 text-sm text-muted">{a}</dd>
          </div>
        ))}
      </dl>
    </>
  );
}
