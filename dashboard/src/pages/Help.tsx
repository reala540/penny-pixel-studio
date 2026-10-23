import { PageHeader } from "../components/ui";

const FAQ: [string, string][] = [
  ["What happens each week?", "Saturday morning the studio collects news and data and picks ideas. Sunday it writes, checks and renders the videos. Sunday evening you get a Telegram message. You review on Monday, and approved posts go out during the week."],
  ["Why does a video say \"Needs a look\"?", "An automatic check found something: a fact without a source, a phrase that sounds generic, or a length problem. Open it in Review Studio; the box at the top lists exactly what to check."],
  ["What does \"Post it yourself\" mean?", "The platform didn't let the studio post automatically (for example before YouTube or TikTok approve the app). Download the approved file from Review Studio, post it, then press Done in Home."],
  ["What does \"Check on the platform\" mean?", "The upload was interrupted and the studio can't tell if it finished. Look on the platform first. If the post is there, record it with Done; if not, press Try again in Calendar."],
  ["Why was a post blocked?", "Usually because the facts in it are older than their freshness date. Use \"Re-check the facts\" in Calendar, or reject the package."],
  ["Will this ever charge me?", "Only X costs money, capped by your monthly limit (at most $1). Every other service is used on its free tier, and when a free allowance runs out the studio waits or uses another free service."],
  ["How do I stop everything?", "Press Pause publishing on Home, or send /pause to your Telegram bot."],
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
