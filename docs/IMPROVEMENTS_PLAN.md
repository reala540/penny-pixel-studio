# Improvements: what exists, what's missing, and a phased plan

Report for to-do items 18–22c. **Status: all five phases built** (PRs for phases 1–5); the notes below describe what each one does.
Checked against the code and the live studio on 28 Oct 2026.

## Summary

| Item | Today | Gap | Phase |
|---|---|---|---|
| 18 Search and discovery packaging | Titles, descriptions with real sources, tags, thumbnail texts, X and Facebook posts, Shorts captions and hashtags are written for every package | No audience, search question or search phrases; the same Shorts caption goes to YouTube, TikTok and Facebook; tags and hashtags can't be seen or edited in Review; few platform-limit checks before approval | 1 and 4 |
| 19 Older backlog | AI cost per call and render time are already recorded | No affiliate offers, no revenue, no cost-per-video view, no analytics feedback | 3–5 |
| 20 Boost suggestions | Nothing | Needs real performance numbers first (22a) | 4 |
| 21 Backup free AI service | **Already done.** Mistral is connected and was used 39 times in the last two weeks, alongside about 20 other free services (Gemini, Groq, Cloudflare, OpenRouter, OVH, Ollama…) | Nothing to do | — |
| 22a Performance page | YouTube read-only analytics permission is already granted | No code reads or shows any numbers | 3 |
| 22b Animated scenes | Every scene is one still card (Pillow) with a slow zoom (FFmpeg), plus captions | No moving explanations | 2 |
| 22c Free visual sources | Stock **photos** from Pixabay, Pexels and Openverse, each with a licence record | No video clips, sound effects or icon sets | 1 and 2 |

## 18. Search and discovery packaging

**What exists**
- `script/pipeline.py make_package` writes: YouTube title (under 70 characters, honest), a 3-paragraph description with
  a sources line filled from the claims that passed checking, 10–15 tags, 3 thumbnail texts, an X post (under 270,
  no links), a Facebook post (60–120 words), and two Shorts with their own caption and 3–5 hashtags.
- Checks today: banned generic phrases, claimed hands-on tests, X length and links, money disclaimer, country-specific
  titles for money videos.
- Research already uses current evidence: Google Trends RSS, Google News, YouTube search, Reddit, Hacker News and
  official feeds feed the idea score ("demand", "trend momentum"). No search-volume numbers are invented.
- Review lets the owner edit each post's title and text.

**What's missing**
- No stored audience, search question, primary phrase or supporting phrases per topic.
- One Shorts caption for every platform (YouTube Short, TikTok, Facebook Reel). Only YouTube adds `#Shorts`.
- Tags and hashtags aren't shown in Review, so they can't be edited.
- Limits checked only for X. Not checked: YouTube title 100 and description 5,000 characters, tags 500 characters in
  total, TikTok caption 2,200, Facebook Reel description, hashtag counts.
- No keyword-stuffing or off-topic-hashtag check.

**Plan**
1. Add a small "search brief" per package: audience, the question they'd type, one primary phrase, 3–6 supporting
   phrases, taken from the idea's own research. It is labelled "not measured" because no search volumes exist.
2. Ask the writer to use the primary phrase naturally in the title, the first line of the description, the hook and
   the on-screen words. Add a check that flags it if the phrase appears more than about 3 times (stuffing).
3. Platform-specific captions: YouTube Shorts, TikTok and Facebook Reels each get their own short caption and 2–5
   hashtags that relate to the topic. No trending tags unless the research shows the topic itself is trending.
4. Before approval, check every platform limit and show problems in "Check before approving".
5. Review: show and edit the search brief, tags and hashtags next to each post.

## 19. Older backlog

**What exists:** `provider_usage` records each AI call (most are free, so cost is $0) and render seconds; GitHub
minutes are recorded; the X budget is tracked.

**What's missing and the plan**
- **Cost per video** (phase 3): one line per package showing AI calls, render minutes, X spend, total.
- **Revenue per video** (phase 3): from YouTube Analytics' revenue report once the channel earns. The permission is
  already granted. Shown as "not available yet" until then.
- **Analytics feedback** (phase 4): see 22a and 20.
- **Affiliate offers** (phase 5, needs you): you'd join programmes (for example a budgeting app or an AI tool you
  really use) and paste your links in Settings. The writer may then mention a matching offer, with a clear "affiliate
  link" disclosure as US FTC rules require. It is never in money advice that could be read as a recommendation for
  someone's personal situation.
- **Original visuals:** covered by 22b.

## 20. Boost suggestions

Needs 22a's numbers. Plan (phase 4): once a post clearly beats your own average for its platform (for example
reach after 48 hours), Telegram and the Performance page say "worth boosting". You press Boost in Facebook yourself
and set your own budget. The studio never spends money.

## 22a. Performance page

**What exists:** the YouTube connection asked for `yt-analytics.readonly` and `yt-analytics-monetary.readonly`.

**Plan (phase 3)**
1. A daily read-only collector (inside daily maintenance) stores per-video numbers: YouTube views, watch time, average
   view duration, impressions and click-through rate, subscribers gained, top countries.
2. A Performance page: per-post table, AI vs Money, Reels vs long videos, best days and times, top countries.
   Missing numbers say "not available" or "not collected yet".
3. Facebook: add the Page insights permission to the Facebook app, then reach, views and engagement per post.
4. Later, with Instagram and TikTok connected: their per-post numbers.
5. X: off by default, because reading stats through X's API costs money.
6. Optional weekly Telegram summary.

## 22b. Livelier videos: a few animated scenes

**How videos are made today:** the script's scenes each have a `visual` (title card, stat, chart, list, quote,
stock photo, steps or comparison). `render.py` draws each one as a still image with Pillow, turns it into a clip with
FFmpeg's slow zoom and fade, joins the clips, and burns in captions. Each clip is cached by a hash, so an unchanged
scene is never drawn twice.

**Proposal (phase 2), small and compatible**
- A new visual type, `animated`, with a few original templates in Penny's and Pixel's colours:
  - coins moving between budget jars;
  - a shopping basket whose total ticks up as prices rise;
  - AI agents passing a task card along a line;
  - a bar or number that grows to the real figure.
- Each template draws its frames with Pillow (already installed; no new software or paid service), then FFmpeg joins
  them. Charts keep their exact figures from the fact sheet; captions stay readable over a calm band.
- The writer may pick `animated` for 2–4 scenes per long video and at most 1 per Short, only where movement explains
  the sentence. Everything else keeps today's visuals.
- **Preview and replace one scene:** in Review → Script, each animated scene gets "Preview this scene" (renders just
  that scene) and "Try another animation" (switches template or settings). The cached clips mean the full video is
  rebuilt in about a minute without changing narration, captions or the other scenes. Approval rules are unchanged:
  a changed scene is a new script version and needs approval again.

**Computing needs:** about 20–40 seconds of the GitHub computer's time per animated scene at preview quality, and
about double at final quality. With 2–4 per video that adds roughly 1–3 minutes per video, within today's free
GitHub minutes. No graphics card needed. (Manim or Blender would look fancier but need extra installs and far longer
renders; they're not proposed now.)

## 22c. More free visual and sound sources

**What exists:** `media/stock.py` searches Pixabay, then Pexels, then Openverse for **photos**, stores a licence
record for each, and falls back to typographic cards.

**Plan**
- Phase 1: **real video clips** from Pexels and Pixabay (same keys you already have). A stock scene can use a short
  clip trimmed or looped to its narration, with a licence record, before falling back to a photo.
- Phase 2, with the animations: Iconify icons (no key) for animated scenes; Freesound sound effects (free key, CC0 or
  CC-BY only, credited); then Unsplash, Coverr, Smithsonian Open Access, NASA and Wikimedia Commons as further fallbacks.
  Unclear licences are skipped.

## Phases

| Phase | What | Needs from you |
|---|---|---|
| 1 | Platform limits before approval; tags and hashtags visible and editable in Review; per-platform Shorts captions; stock **video** clips from Pexels and Pixabay | Nothing |
| 2 | Animated scenes (4 templates) with preview and replace one scene; Iconify icons; Freesound effects | A free Freesound key |
| 3 | Performance page (YouTube first); cost per video; revenue once earning | Add the Facebook insights permission later |
| 4 | Search brief per package; packaging that learns from real results; boost suggestions | Nothing |
| 5 | Affiliate offers with disclosure | Your affiliate links |

E (review after about a month) needs about a month of posting, so it can't be done yet. A reminder can be set for
around 27 Nov 2026.
