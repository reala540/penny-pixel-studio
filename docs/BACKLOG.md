# To-do list

The owner's running list of what's left, in the order we plan to do it. "You" means the owner; "Claude" means the
coding assistant. Tick items off by editing this file.

## A. Right now: finish what's in progress

1. [ ] **You:** merge PR #25 (Facebook Stories and long videos). Its tests are green.
2. [ ] **You:** run **GitHub → Actions → First-time setup → keys only** (adds the Story post type, migration 16).
3. [ ] **Claude:** check from the database that migration 16 landed.
4. [ ] **You:** Settings → Posting schedule → Facebook Page: set Stories per week (e.g. 3) and Long videos per week
   (e.g. 1), then Save. Add a posting day or time if the week is full.
5. [ ] **You:** Settings → Accounts → X: change the saved handle to **@PennyAndPixel**.
6. [ ] **You:** Facebook Page tidy-up: change the X link to `https://x.com/PennyAndPixel`, upload the new cover
   (`brand-assets/penny-pixel-facebook-cover-1640x924.png`), delete the stray pink "P" photo if not wanted.
7. [ ] **You:** personal Facebook profile: friend requests from "Friends of friends" only, friends list "Only me";
   do following and commenting as the Page.
8. [ ] **You:** buy the smallest X API credits with auto-recharge **off** (otherwise X posts become copy-and-paste tasks).
9. [ ] **Claude (offered):** on Mon 2 Nov evening, check the first three posts (X 17:30, YouTube AI 18:00,
   Facebook 19:00 New York time) went out.
10. [ ] **You, after each YouTube upload:** switch it from Private to Public in YouTube Studio (until Google audits
    the app).

## B. Next builds

11. [ ] **Instagram**
    - You: create the account (e.g. @pennyandpixel), switch to Professional → Creator, link it to the Penny & Pixel
      Page, add the Instagram permissions to the Facebook app, then press Connect in the studio.
    - Claude: add Instagram to the studio: Reels/Shorts, Stories (3 hours after the Reel), long videos as Reels,
      and text posts as branded picture cards. Each has its own "per week" number, starting at 0. Same Telegram
      alerts and evening heads-up. One migration, one PR, tests with a fake Instagram only.
    - You: turn on notifications in the Instagram app for messages, comments and followers (Instagram doesn't
      share those with outside apps).
12. [ ] **TikTok**
    - You: create the TikTok account and a TikTok developer app (Login Kit + Content Posting API), paste its keys in
      Setup, press Connect.
    - Until TikTok approves direct posting, videos arrive in the TikTok inbox as drafts to tap and post.
    - Later: apply for TikTok's audit so posts go out by themselves.

## C. Getting paid (later)

13. [ ] **YouTube payouts:** channel country United States; AdSense with US address, US bank account and US tax form
    (W-9); YouTube Partner Program once eligible.
14. [ ] **Facebook monetization:** Page → Professional dashboard → Monetization once eligible (Reels ads, in-stream
    ads on long videos, Stars).
15. [ ] **Instagram earnings:** Gifts (~500 followers), brand deals (~1,000), Subscriptions (~10,000), shown under
    the Instagram Professional dashboard.
16. [ ] **Money set-up:** US bank account and a US PayPal (keep the Kenyan one for Kenya only).
17. [ ] **Before turning on any payouts:** check with an immigration adviser that your US visa or status allows this
    income; keep records for US taxes.

## D. Improvements to plan (report first, no changes until agreed)

18. [ ] **Search and discovery packaging (SEO).** First a report: what exists, what's missing, and a phased plan.
    Requested scope:
    - For each topic: intended audience, their likely search question, one primary search phrase, relevant
      supporting phrases, used naturally in title, description or caption, and script.
    - Never invent search-volume data or claim a topic is trending without current evidence.
    - YouTube: clear, compelling title; useful description with relevant opening lines and sources; relevant tags;
      thumbnail text that complements the title.
    - Shorts, TikTok, Reels: strong opening; clear spoken and on-screen topic wording; concise caption; a small set
      of relevant hashtags suited to the platform.
    - Facebook and X: clear opening and a useful native post adapted to each platform.
    - Avoid keyword stuffing, unrelated trending hashtags, misleading claims, engagement bait and identical copy
      everywhere. Check platform limits before approval.
    - Show proposed title, caption, keywords and hashtags in the existing Review screen, editable.
    - Keep factual accuracy, brand voice, approvals and publishing safeguards.
    - Check which analytics the app really supports; where available use impressions, click-through rate, watch time,
      retention and meaningful engagement to improve future packaging; label missing data clearly; never invent
      results or promise virality.
19. [ ] **Stage 3 (older backlog):** affiliate offers, an analytics feedback loop, cost and revenue per video,
    original visuals.
20. [ ] **Boost suggestions:** the studio suggests which post is doing well enough to boost; you press "Boost" in
    Facebook yourself with your own budget. The studio never spends money on ads.
21. [ ] **More AI services:** add another free AI provider (e.g. Mistral's free Experiment plan) so the voice editor,
    critic and angle-selector steps have a backup.
22. [ ] **Second clock (done)** — the header now shows studio time and Kenyan time.

22a. [ ] **Performance page in the app** (plan together with 18 and 19; report first, no changes until agreed).
    One place to monitor everything instead of opening each platform:
    - YouTube (permission already granted, read-only): views, watch time, average view duration and retention,
      impressions and click-through rate, subscribers gained, top countries, and later revenue.
    - Facebook Page: reach, views, watch time and engagement per post (needs the Page insights permission added to
      the Facebook app).
    - Instagram (once added): reach, plays, saves, shares per Reel and Story (needs the Instagram insights permission).
    - TikTok (once added): views, likes, comments and shares per video, as far as TikTok's API allows.
    - X: per-post stats cost money to read through X's API, so they'd be off by default or shown as "not
      available" rather than spending the X budget.
    - Comparisons: AI vs Money, Reels vs long videos, best days and times, top countries (for the UK slot decision).
    - Every missing number is labelled "not available" or "not yet collected", never guessed; no promises of virality.
    - Read-only: looking at the page never posts, approves, generates or spends anything.
    - Optional: a weekly Telegram summary of the same numbers.

22b. [ ] **Livelier videos: a few original animated scenes** (review and proposal first, no changes until agreed).
    - Videos feel like slideshows (still pictures, charts, big text). Keep those where they help, and add a few
      original animated scenes that illustrate exactly what the narrator says, e.g. coins moving between budget
      categories, a shopping basket changing as prices rise, AI agents passing tasks between themselves.
    - A balanced mix, not all motion graphics. Movement explains something, never just decorates. Modern, polished,
      consistent with Penny's or Pixel's branding. Factual charts stay accurate; captions stay readable.
    - Free tools and libraries only, building on the existing renderer. No paid APIs, no trial credits, no copying
      other creators' videos or distinctive styles. Explain any extra computing needs before choosing.
    - First review how scenes are planned, assets are sourced, and previews and final videos are rendered; propose a
      small, compatible addition that keeps existing videos, narration, captions, approvals and publishing working.
    - Include a way to preview and replace one animated scene without regenerating the whole video.
    - Also consider short real-world stock video clips (b-roll) from Pexels and Pixabay, which the studio already
      has keys for (it uses them for photos today), with the same licence records as photos.

## E. Review after about a month of posting

Until the Performance page exists, do this by hand in each platform's own stats (YouTube Studio → Analytics,
Facebook Professional dashboard → Insights, X post analytics, TikTok and Instagram in-app insights).

23. [ ] Check each platform's Insights/Analytics for where viewers are. If the UK is big, add a lunchtime slot
    (about 12:00 New York, 17:00 London).
24. [ ] Long videos on Facebook and Instagram: keep or drop based on views.
25. [ ] Split X or Facebook into separate AI and Money accounts only if one side clearly takes off.

## F. Small technical notes

26. [ ] If the saved timezone were ever an unknown name, dates on some pages would break (the Settings picker only
    offers real zones, so this needs a database edit to happen). Harden later.
27. [ ] Turn on Supabase "leaked password protection" if the project ever moves to Supabase Pro.

## Appendix: original request for item 22b (word for word)

Again, I want to improve the visual experience of generated videos. Currently, they feel too much like slideshows, with
still pictures, charts, and large text. Keep those visuals where they help, but add a few original animated scenes
throughout each video to make the explanations more engaging.

I do not want the entire video to become motion graphics. Use a balanced mix of existing visuals and occasional
animation that directly illustrates what the narrator is saying. For example, coins moving between budget categories, a
shopping basket changing as prices rise, or AI agents passing tasks between themselves.

These scenes should feel modern, polished, and consistent with Penny's or Pixel's branding. Movement should explain
something, rather than simply decorate the screen. Keep factual charts accurate and captions readable.

Use free tools and libraries, preferably building on the existing rendering workflow. Avoid paid APIs, trial-credit
dependencies, and copying other creators' videos or distinctive styles. Explain any additional computing requirements
before choosing the approach.

First review how the app currently plans scenes, sources assets, and renders previews and final videos. Propose a small,
compatible addition that preserves existing videos, narration, captions, approvals, and publishing. Include a way to
preview and replace an animated scene without regenerating the whole video.
