# Test report — v2.6 Five pages and Create one package (24 Oct 2026)

| Suite | Result |
|---|---|
| Engine (pytest, local PostgreSQL with all 9 migrations, real renders) | **115 passed** (11 new: only the chosen idea is made; distribution and Auto Review & Post touch only that package while other packages stay unapproved; a generated idea keeps its sources and pressing twice changes nothing; two simultaneous requests make one research idea and one package; a busy production lock is refused with a plain message; bad requests explained; a failed package resumes from its step with no duplicate posts; publishing pause doesn't block it; the weekly batch doesn't remake an idea that already has a package; the owner job is linked to its package; **Test again** saves a fresh key check) |
| Worker (vitest + `tsc`) | **46 passed** (unchanged) |
| Dashboard (vitest + `tsc` + build) | **31 passed** (10 new: every old link and OAuth return redirect; readiness blockers vs warnings, stale checks, uncovered jobs; progress shows only real stages and their stored errors) |
| Browser (Chromium, real PostgREST + real local Worker, desktop 1440×900 and phone 390×844) | **80/80 checks**, 0 console errors: five destinations and the secondary menu; approval mode in the menu and before Create package (manual and Auto ON); 12 old links and both OAuth returns; Create flow end to end (owner job carries exactly the chosen idea; waiting, engine-reported step, real stage list, stored error, Try again; both channels = ideas only; an already-made idea links to its package); stale check + Test again; no passing service blocks with the reason; one passing service doesn't claim full coverage; pause banner and Create still allowed; no Telegram still allowed; a real GitHub refusal blocks with the reason; Content tabs, filters, project page tabs, breadcrumb and confirm wording; Activity quick actions and collapsed Technical details; Settings sections; no sideways scroll on 8 phone pages |
| npm audit | 0 vulnerabilities (dashboard, worker) |

Not verifiable here: a real production run against live AI services (the live studio's Evidence scout services are
currently failing; see the PR for the evidence) and the live migration, which is applied only after merging.

## v2.5 Setup, Activity, schedule, auto-fix and Clear (24 Oct 2026)

| Suite | Result |
|---|---|
| Engine (pytest, local PostgreSQL with all 8 migrations, real renders) | **104 passed** (13 new: fixes switched off go straight to you; an unsure review queues a rewrite with the reviewer's notes and nothing posts meanwhile; the rewrite runs in the same queue run and the package is then approved; post text fixed in place (banned phrase + disclaimer) then approved; policy flags and wrong accounts never retried; attempts stop at the limit; a missed slot moves to the account's next free slot without clashes; schedule edits validated, owner-only, audited and kept across config syncs; waiting posts moved to new slots; dashboard-saved secrets win and unreadable ones are reported; presence recorded only in GitHub Actions; no client can read saved secrets; live progress and tracked weekly runs) |
| Worker (vitest + `tsc`, `wrangler deploy --dry-run` 57.6 KiB) | **46 passed** (9 new: setup endpoints owner-only; values encrypted, never returned, audited by hint only; bad pastes refused with plain advice; saving the bot token creates the webhook secret and links the bot; dashboard value used instead of GitHub; Google pair check; status shows where each value lives without values; remove falls back; webhook accepts either owner secret and nothing else) |
| Dashboard (vitest + `tsc` + build) | **21 passed** (8 new: schedule preview, shared Facebook slots, warnings, pause, junk values; timeline merge and filters; a fix for every problem; Clear only hides what existed) |
| Browser (Chromium, real PostgREST + real local Worker) | **66/66 new checks**, 0 console errors: Simple menu and Advanced switch saved per studio; first-time tour and replay; plain panel names with "?"; clear objective/finished jobs/history with Undo; running job with step and progress bar, menu indicator; problem with fix button; Setup live checks, copy redirect, encrypted save with hint only, engine reads the Worker's encryption, bad paste refused, remove; schedule edit, preview, audit, reset, warning; fix attempts; AI API labels; usage reset as a view setting with Undo; clear new ideas and Undo; cancel a post and Undo; no sideways scroll at 375 px. Earlier suites: **19/19** Auto Review & Post, v2.3 **56/58** (the 2 misses are test-state assumptions, both behaviours re-checked by hand and working) |
| npm audit | 0 vulnerabilities (dashboard, worker) |

Bugs found and fixed by these tests: cleaning a post's text erased the disclaimer added in the same fix; moving a
missed slot updated the wrong row (column name clash); "content expired" pointed to *Reconnect* instead of
*Re-check the facts*; two buttons were both called "Clear"; cancelled jobs cluttered the timeline; Deploy Worker would
have re-registered Telegram with the GitHub webhook secret and locked out a Setup-page secret.

Not verifiable here: real platform sign-ins, real Telegram delivery and real provider key checks run when you use
Setup with your own accounts (the YouTube key check did reach Google from the local Worker and reported the test key
as invalid, as expected).

## v2.4 Auto Review & Post (24 Oct 2026)

| Suite | Result |
|---|---|
| Engine (pytest, local PostgreSQL with all 7 migrations, real renders) | **91 passed** (8 new: OFF keeps the manual flow exactly; ON approves only fully passing packages and the publish guards accept them; low confidence and review errors fall back to manual with Telegram; needs-attention and expiring facts never auto-approve; switching OFF mid-review stops approval; OFF returns unpublished auto-approvals; only owner/Worker/engine can switch, never a direct write) |
| Worker (vitest + `tsc`) | **37 passed** (8 new: status and /status, ON needs confirm, ON via the audited function + one review job, OFF reports reverted posts, other chats ignored, dashboard endpoint owner-only with confirm, saved mode reported even if Telegram is down) |
| Dashboard (vitest + `tsc` + build) | **13 passed**, build clean |
| Browser (Chromium, real PostgREST + real local Worker + real Telegram webhook calls) | **19/19 new checks** (default OFF shown everywhere, confirm/cancel, persists, audited, review queued, Telegram OFF/ON sync to the dashboard without reload, unlinked chat refused, direct write refused, OFF persists) and **58/58** v2.3 checks still passing, 0 console errors |
| npm audit | 0 vulnerabilities |

Bugs found and fixed by these tests: the switch function trusted `current_user` (always the function owner) and
would have let any signed-in user call it; the Worker reported an error after a successful switch when Telegram was
unreachable.

## v2.3 Ideas, themes and AI API Manager (24 Oct 2026)

| Suite | Result |
|---|---|
| Engine (pytest, local PostgreSQL with all 6 migrations, real FFmpeg/Kokoro renders) | **83 passed** (27 new: key strategies, caps, quota groups, retries/backoff, failover, concurrency, secrecy, DB encryption; idea weights, measured trend, evidence, dedupe, unverified labels, approval boundary, queue, refine, config; column-level security) |
| Worker (vitest + `tsc`, `wrangler deploy --dry-run`) | **29 passed** (9 new: owner-only, server-side encryption, masked responses, authorisation, quota groups, key test, URL safety, schedule slots), bundle 39 KiB |
| Dashboard (vitest + `tsc` + Vite build) | **13 passed**; Ideas and AI API Manager are lazy-loaded chunks |
| Browser end-to-end (Chromium, real PostgREST + the real Worker running locally) | **58/58 checks, 0 console errors**: theme switching, persistence, no flash, System follows the device, every page in dark, keyboard control; 10 ranked ideas, 70-point breakdown, dated evidence, save/reject/refine, Send to Studio → edited objective → research queued, idea marked sent, no production created, one job per press; library filters/search/history; add two keys for one provider, masked hint, encrypted at rest, quota groups, honest key test, caps, strategy, model jobs, replace, remove; no full key in any response or page; schedule and categories saved; no horizontal scroll at 390 px |
| npm audit | **0 vulnerabilities** (dashboard, worker) |

Not verifiable here (no outbound access from the build container): real AI calls through added keys and real research
fetches. Both use the same code paths the tests exercise with recorded responses; the first live run shows its notes
in the Idea Library.

## v2.2 Mission Control upgrade (24 Oct 2026)

What changed: Mission Control (owner-directed missions, live model activity, run queue, readiness, public `/demo`),
concurrent research collection, per-job attribution of model calls, activity indexes (migration 5), run locks so
batches never overlap, longer owner-request timeout, light/dark Mission Control theme, lazy-loaded pages, and
security dependency upgrades.

| Suite | Result |
|---|---|
| Engine (`engine/tests`, pytest, local PostgreSQL with all 5 migrations, real FFmpeg/Kokoro renders) | **56 passed** |
| Worker (vitest + `tsc`, `wrangler deploy --dry-run`) | **20 passed**, type-check clean, bundle 26 KiB |
| Dashboard (vitest + `tsc` + Vite 7 build) | **8 passed**, build clean; Mission Control is a separate 24 kB chunk |
| Dependency audits (`npm audit`) | **0 vulnerabilities** in dashboard and worker (was 5 incl. 3 high, and 12 incl. 2 critical) |
| Lockfiles | Regenerated from `registry.npmjs.org` only; `npm ci` with the CI's npm 10 verified |
| Tailwind parser override | CSS output byte-identical before and after |
| Browser (Chromium/Playwright, signed in against a real PostgREST on the real schema) | **28/28 checks, 0 console errors**: live calls and failures shown, stage filter, launch mission, cancel queued job, pause feed, all 8 pages, no horizontal scroll at 390 px in light and dark, public demo makes no database calls, reduced motion respected |

Dependency choices: versions are the oldest that carry the security fixes, mostly 2+ weeks old
(react-router-dom 7.18.4, supabase-js 2.109.0, vite 7.3.7, postcss 8.5.28, wrangler 4.148.0, workers-types
5.20261008.1). vitest 4.1.12 and undici 7.30.1 are newer (9 days) because they are the only patched releases; both
are build/test tools, not shipped to users.

## Historical report — v2.1 MVP (23 Oct 2026)

## What was run

| Suite | Result | What it covers |
|---|---|---|
| Engine (`engine/tests`, pytest) | **36 passed** (9 min) | Router fallback, quotas, circuit breakers, JSON repair, 402 handling; quality gates; claim verification; scoring and experiments; timezone scheduling; migrations, RLS, immutability, budget cap, job runner; full journeys (below) |
| Worker (`worker/test`, vitest) | **15 passed** + `tsc` clean | Owner-only dispatch, non-owner rejection, OAuth state encryption and forged-state rejection, Telegram secret/link/pause/resume-confirm, cron only wakes GitHub when work is due, pause respected, Python↔Worker token encryption compatibility |
| Dashboard (vitest + `tsc` + `vite build`) | **5 passed**, build clean | Timezone/day helpers, rescheduling math, status tones, safe external links |
| Browser click-through (Playwright, real PostgREST on the real schema) | **passed, 0 console errors** | Sign-in + ownership claim, approve package (7 posts scheduled via `approve_project`), edit caption, reschedule (09:15 Nairobi saved as 06:15 UTC), pause publishing; screenshots of all 6 pages, desktop and mobile, light and dark; no horizontal overflow on mobile |
| Live Supabase project `penny-pixel-studio` | migrations 1–3 applied; 34 tables, RLS on all, 54 policies, private bucket | Security advisor: only intentional findings (token table has no client policy by design; owner-only RPC functions check `is_owner()`) |

## The eight blueprint journeys (engine/tests/test_end_to_end.py)

1. Research → Script → Video → Review ✅ (RSS parsing and dedupe; 2 long + 4 Shorts rendered; claims all supported; sources filled into descriptions; disclaimer present; roles split across different providers)
2. Approval → Scheduling → Publishing ✅ (nothing publishes before approval; YouTube private upload + follow-up task; TikTok inbox draft; Facebook and X via API)
3. Provider outage → free fallback ✅ (the failing provider is called once, its circuit opens, others take over)
4. Failed render → resume ✅ (retrying job resumes without regenerating the script)
5. Expired finance data → publication blocked ✅
6. Budget exhaustion → X disabled ✅ (no X API call made; posts become manual tasks)
7. Unverified/unconnected platform → manual fallback ✅
8. Duplicate publish attempt → prevented ✅ (zero extra platform calls on re-run); ambiguous upload → "Check on the platform" ✅

## Benchmark (this build machine: 4 CPU cores)

| Measure | Value |
|---|---|
| Final 1080p render | 1.02 s per second of video (voices cached) |
| Preview 480p render | 0.19 s per second of video (voices cached) |
| Kokoro voice generation | ≈1 s per second of speech, first time only (then cached) |
| Final file size | ≈6 MB per minute |
| Peak memory | ≈780 MB |
| Full weekly plan (6 long + 12 Shorts) | ≈62 render-minutes here; GitHub's 2-core runners are about 2× slower → ≈125–200 min/week incl. voices and AI, within ≈465 free min/week |

Run the **Benchmark** workflow on GitHub to measure your real runner; the capacity planner uses measured speeds.

## What could NOT be verified here (honest limits)

This build environment's network only reaches package registries. So:

- **No real AI provider was called.** The router is tested against simulated OpenAI-compatible responses. The first
  real call happens when you run **First-time setup** (its `studio providers` step tests every key).
- **No real social platform was called.** YouTube, Facebook, TikTok and X adapters follow the official API shapes and
  are tested against mocks. Each platform's first real post should be watched (start with the trailers).
- **Research adapters** were tested with recorded RSS/JSON shapes, not live feeds.
- **The Worker was not deployed** (no Cloudflare credentials here); it is deployed by the *Deploy Worker* workflow.
- Migration 4 (performance indexes) timed out through the Supabase connector; it is applied automatically by
  `studio migrate` in the first-time setup workflow.
- Model names and free limits come from community lists dated Oct 2026; providers change them often.

## Security review

A focused security review of the whole branch found no high-confidence vulnerabilities. One hardening fix was
applied: links from outside research feeds are only stored and shown if they are `http(s)` URLs, so a hostile feed
can't plant a `javascript:` link in the dashboard.

## Live deployment checks (23 Oct 2026)

| Check | Result |
|---|---|
| Supabase `penny-pixel-studio` | 4/4 migrations applied and recorded; 34 tables with RLS; 54 policies; 11 extra indexes; private `studio` bucket; starting configuration loaded (1 brand, 2 channels, 5 accounts + connection rows, 13 AI providers, 21 models, $1 X budget, 6 settings) |
| Vercel project `dashboard` | Production build from `main` **READY** (vite build 4 s); live at https://dashboard-beta-ten-13.vercel.app |
| Live routes | `/`, `/review`, `/privacy` return 200 with the SPA and security headers (X-Frame-Options DENY, nosniff, HSTS, referrer and permissions policy) |
| Live bundle | Points at `https://eazmczmnunzrmrpsrhvx.supabase.co` |
| Git history | All commits authored by reala540 <atonymutembei@gmail.com> (required by Vercel Hobby; earlier deployments were blocked for a different author) |
