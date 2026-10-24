import { PageHeader } from "../components/ui";

const FAQ: [string, string][] = [
  ["What happens each week?", "Saturday morning the studio collects news and data and picks ideas. Sunday it writes, checks and renders the videos. Sunday evening you get a Telegram message. You review on Monday, and approved posts go out during the week."],
  ["Why does a video say \"Needs a look\"?", "An automatic check found something: a fact without a source, a phrase that sounds generic, or a length problem. Open it in Review Studio; the box at the top lists exactly what to check."],
  ["What does \"Post it yourself\" mean?", "The platform didn't let the studio post automatically (for example before YouTube or TikTok approve the app). Download the approved file from Review Studio, post it, then press Done in Home."],
  ["What does \"Check on the platform\" mean?", "The upload was interrupted and the studio can't tell if it finished. Look on the platform first. If the post is there, record it with Done; if not, press Try again in Calendar."],
  ["Why was a post blocked?", "Usually because the facts in it are older than their freshness date. Use \"Re-check the facts\" in Calendar, or reject the package."],
  ["Will this ever charge me?", "Only X costs money, capped by your monthly limit (at most $1). Every other service is used on its free tier, and when a free allowance runs out the studio waits or uses another free service."],
  ["How do I stop everything?", "Press Pause publishing on Home, or send /pause to your Telegram bot."],
  ["How are idea scores worked out?", "70 of the 100 points come from real, dated sources the idea cites: how many independent sources, how recent, how strong the signal. The other 30 are an AI reviewer's opinion of originality, international relevance, feasibility and engagement. An idea with no current source is marked Trend unverified. Press Why this score on any idea to see the sources."],
  ["Does generating ideas start making videos?", "No. Ideas go to the Idea Library. A video is only made when you send an idea to the Studio, launch it, and later approve it in Review."],
  ["Can I add more than one key for an AI service?", "Yes, in AI APIs. Each key has its owner, limits and health. Keys from the same account share one limit, so the studio won't switch between them to get around a limit; tick \"separate account\" only for a key that really has its own allowance."],
  ["What is Auto Review & Post?", "OFF (default): you approve everything. ON: the AI approves only packages that pass every check (quality, sourced facts, freshness, the right accounts, licences, and a confident independent policy review); they post at their normal times. Anything else waits for you and comes to Telegram. Switch it in Settings → Automation or with /autopost in Telegram."],
  ["How do I switch to dark mode?", "Use the sun / moon / screen buttons at the bottom of the menu, or Settings → Appearance. Screen follows your device."],
];

export default function Help() {
  return (
    <>
      <PageHeader title="Help" intro="The full step-by-step guide is GUIDE.md in your GitHub repository. These are the questions that come up most." />
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
