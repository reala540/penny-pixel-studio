# AI Content Studio v2.1 — Free-First Production Edition

**Status:** authoritative specification. Where `APPENDIX_PROVIDERS.md` (the original 14-provider map) disagrees with this document, this document wins.

**Brand:** Penny & Pixel. Two hosts, five accounts:

| Account | Host / focus | Weekly target |
|---|---|---|
| YouTube "Penny & Pixel AI" | Pixel: AI tools, explainers, AI news, tutorials | 3 long videos + 6 Shorts |
| YouTube "Penny & Pixel Money" | Penny: personal finance, careers, economics | 3 long videos + 6 Shorts |
| Facebook Page "Penny & Pixel" | Mix (starts 50/50) | 3 Reels + 2 posts |
| TikTok @pennyandpixel | Mix (starts 50/50) | 3 videos |
| X @pennyandpixel | Mix (starts 50/50) | 3 posts |

Targets are goals. Quality gates and the capacity planner may lower them; they never raise spending.

---

## 1. Budget rules (non-negotiable)

- $0/month for everything except X.
- X: at most $1.00/month. Each post reserves its estimated cost (config: $0.015; links are blocked) *before* the API call, in one database transaction (`reserve_budget`). Reservations are committed on success, released on a definite failure, and kept on an ambiguous failure. The owner cannot raise the cap above $1 (enforced by a database policy). Local enforcement can't stop charges made outside the app, so the owner also sets X's own spending limit.
- Any provider returning *payment required* (402) is switched off for 24 hours. A paid model is never used.
- Every adapter has an on/off switch, commercial-use flag, configured limits, usage tracking, last success, circuit breaker and fallback.

## 2. Architecture

| Component | Service (free) | Notes |
|---|---|---|
| Dashboard | Vercel (Hobby) — Cloudflare Pages is the free commercial-use alternative | Static React app; holds only the public anon key |
| Light backend | Cloudflare Workers | OAuth connect flows, Telegram webhook, owner-only "run now" dispatch, 15-minute cron that wakes GitHub only when work is due (10 ms CPU limit respected: no heavy work) |
| Database, login, files | Supabase | Postgres + RLS, Auth (single owner), private Storage bucket `studio` |
| Research, AI, rendering, publishing | GitHub Actions (private repo) | Python engine `studio`; optional self-hosted runner on the owner's computer |
| Video | FFmpeg, Kokoro TTS (Apache-2.0), Pillow, Matplotlib | CPU only, no paid media APIs |
| Alerts | Telegram bot | Owner-linked chat only |

Persistent job rows are the source of truth. Every stage has a job ID, project ID, idempotency key, input, output, attempts, retry policy, timestamps, error kind, provider usage and resume ability. States: pending, queued, running, completed, needs_review, blocked, retrying, failed, cancelled, expired.

Script versions are immutable (database trigger); edits and rewrites create new versions.

## 3. Weekly cycle (timezone Africa/Nairobi, configurable)

- **Saturday 08:17:** research → idea pitches from several free models → scoring with explanations → shortlist (≈30% experiments).
- **Sunday 07:17:** capacity check → scripts → claim verification → voice edit → critic → previews (480p) → thumbnails → Shorts → per-account posts → posting plan (all *waiting for approval*) → Telegram "week ready".
- **Monday:** owner reviews in Review Studio, then approves, edits, rewrites with a note, skips or rejects. "Approve all" only covers items that passed every check.
- **Mon–Sun:** the Worker cron finds due approved posts and starts the publish workflow. The final 1080p video is rendered from the stored recipe at publish time.
- **Daily 02:47:** cleanup, token health checks, freshness expiry; Sundays: database backup artifact.

## 4. Research and scoring

Sources: Google News RSS, Google Trends RSS, Hacker News (Algolia API), official feeds (Google AI, OpenAI, Hugging Face, Federal Reserve, BLS, Central Bank of Kenya), Reddit RSS, YouTube Data API search (optional key), FRED (optional key), SEC EDGAR (user agent required), Wikipedia. Each record stores title, publisher, URL, publication time, retrieval time, event date when known, credibility class, topic, freshness expiry and verification status. All fetched text is untrusted: it is only placed inside `<source>` tags, with an instruction never to follow it.

Score = weighted features (config/research.yaml): audience relevance, search demand, trend momentum, freshness, originality (1 − similarity to past topics; repeats penalised ×0.3), evidence, brand fit, competition, monetization, feasibility, history (neutral 0.5 until enough data). Each idea gets a plain-language explanation.

## 5. Script pipeline (adaptive, multi-model)

1. **Fact sheet** (research_summarizer). Code drops any fact whose numbers aren't in its cited source text. Fewer than 3 facts → human review.
2. **Draft once** (scriptwriter): structured scenes (narration, visual type, on-screen text, claim keys), claims list with fact references, 3 alternative hooks.
3. **Structure gate** (code): 6–40 scenes, 4–9 minutes, hook ≤45 words, CTA, scene ≤45 s, numbers must be tied to claims, banned generic phrases, sentence length, repetitive openings, Money disclaimer, no promised returns.
4. **Claim check** (claim_checker, a different provider from the writer). A claim counts as supported only if the checker quotes the source, the quote really appears in the stored text, and every number in the claim appears in the evidence. One AI agreeing with another is never enough.
5. **Targeted rewrites** of failing scenes, at most 2 rounds.
6. **Voice edit** (voice_editor, a different provider): host voice. Code rejects any edit that changes numbers.
7. **Critic** (different provider): hook, originality, clarity, pacing, value (1–10); one targeted fix round if any score is below 7.
8. **Hook pick** (angle_selector), final banned-phrase cleanup, final claim check.
9. **Package** (repurposer): YouTube title/description/tags, three thumbnail headlines, X post (≤270 characters, no links), Facebook post, two purpose-built Shorts (each checked; numbers must come from the fact sheet). `[SOURCES]` in the description is replaced with the real citations, plus the Money disclaimer and AI-narration disclosure.

Anything uncertain becomes *Needs a look* with the reasons listed; it is never auto-approved.

## 6. Video engine

- Recipe = scenes + voice + visual specs + asset references; it is stored forever and can re-render any video.
- Scene-level cache: changing scene 4 re-renders scene 4 and the final join only.
- Presets: 16:9 1080p and 9:16 1080×1920; previews 854×480 and 480×854.
- On-brand cards (title, stat, chart, list, steps, comparison, quote, licensed stock photo), word-timed highlighted captions (ASS/libass), gentle motion, loudness normalisation, optional licensed music with ducking.
- Stock photos only from the Pixabay/Pexels APIs or Openverse (public-domain CC0/PDM only, no key), each with a license record. Publishing is blocked if a photo has no license record.
- Thumbnails: three deterministic templates (bold-left, big-number, split-contrast) plus a phone-feed preview.
- Masters: GitHub artifacts for 14 days; the recipe is permanent. YouTube is not treated as the archive.

## 7. Publishing safeguards

Only explicitly approved variants with an approval record; account must match; never published twice (a `published_posts` row per scheduled post plus a skip-locked claim); expired time-sensitive facts block the post until re-checked; ambiguous failures (connection dropped after upload) go to *Check on the platform*, never a blind retry; auth failures mark the account *Reconnect needed* and create a manual task; capability detection decides between `api`, `api_draft` and manual:

| Platform | Until audit/approval | After |
|---|---|---|
| YouTube | Private upload + task "set to Public in Studio" | Public upload (set `api_audited: true`) |
| TikTok | Inbox draft + "tap Post" task | Direct post (set `direct_post_approved: true`) |
| Facebook Page | Graph API Reels + feed posts | — |
| X | Pay-per-use API under the $1 cap | — |

Google OAuth apps must be in **production** status (testing-mode refresh tokens expire after 7 days); daily token health checks warn before publish time.

## 8. Dashboard (MVP: 6 pages + Help)

Home (weekly rundown, waiting items, quick jobs, studio health, pause), Review Studio (video, scenes editor, facts drawer, thumbnails, per-account post text, Shorts, approve/rewrite/reject), Calendar (drag to reschedule, exact time, conflicts, retry, freshness re-check), Research (ideas, score breakdown, sources), Library (search/filter, where posted), Settings (accounts, run now, AI writers, channel voices, budget, timezone, Telegram). Responsive with bottom navigation on mobile, light and dark themes, keyboard focus and reduced motion respected.

**Later (not in MVP):** analytics charts and the 70/30 recommendation engine UI (metrics table exists), engagement inbox (comments tables exist), monetization tracker, natural-language command bar, MCP server.

## 9. Security

Single owner (first sign-in claims ownership; sign-ups are then disabled in Supabase). RLS on every table; the owner cannot read encrypted tokens, mark posts published, run the budget function or raise the X cap. Tokens are AES-256-GCM encrypted with `TOKEN_ENCRYPTION_KEY` (shared by Worker and engine, never in the browser). OAuth state is encrypted with expiry and PKCE for X. The Telegram webhook is verified by a secret header and the linked chat ID. Telegram `/resume` needs `confirm`. Audit log for owner and system actions. Secrets live only in GitHub/Cloudflare secret stores.

## 10. Free capacity

The capacity planner estimates GitHub minutes (from measured render speed), Supabase storage and AI requests before each batch, and shrinks the plan with a clear warning instead of failing halfway. Run the **Benchmark** workflow once to measure your runner.

## 11. Acceptance (what was verified for this MVP)

See `docs/TEST_REPORT.md`.
