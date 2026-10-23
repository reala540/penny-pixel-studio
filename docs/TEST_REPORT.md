# Test report — v2.1 MVP (23 Oct 2026)

## What was run

| Suite | Result | What it covers |
|---|---|---|
| Engine (`engine/tests`, pytest) | **36 passed** (9 min) | Router fallback, quotas, circuit breakers, JSON repair, 402 handling; quality gates; claim verification; scoring and experiments; timezone scheduling; migrations, RLS, immutability, budget cap, job runner; full journeys (below) |
| Worker (`worker/test`, vitest) | **15 passed** + `tsc` clean | Owner-only dispatch, non-owner rejection, OAuth state encryption and forged-state rejection, Telegram secret/link/pause/resume-confirm, cron only wakes GitHub when work is due, pause respected, Python↔Worker token encryption compatibility |
| Dashboard (vitest + `tsc` + `vite build`) | **4 passed**, build clean | Timezone/day helpers, rescheduling math, status tones |
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
