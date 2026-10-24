# Test report — v2.4 Auto Review & Post (24 Oct 2026)

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
