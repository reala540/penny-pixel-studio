# Penny & Pixel Studio — AI Content Studio v2.8

A free-first, mostly automated content studio for two faceless YouTube channels (**Penny & Pixel AI** with host
Pixel, **Penny & Pixel Money** with host Penny), a Facebook Page, TikTok and X.

- **New here?** Read **[GUIDE.md](GUIDE.md)**: step-by-step setup, written for non-coders.
- Specification: [docs/SPEC_v2.1.md](docs/SPEC_v2.1.md) · Architecture: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) ·
  Providers and free limits: [docs/PROVIDERS_AND_LIMITS.md](docs/PROVIDERS_AND_LIMITS.md) ·
  Mission Control: [docs/CONTROL_ROOM.md](docs/CONTROL_ROOM.md) · Ideas, themes and API keys: [docs/IDEAS_AND_API_KEYS.md](docs/IDEAS_AND_API_KEYS.md) · Auto Review & Post: [docs/AUTO_REVIEW_AND_POST.md](docs/AUTO_REVIEW_AND_POST.md) · Setup, Activity and schedule: [docs/SETUP_ACTIVITY_SCHEDULE.md](docs/SETUP_ACTIVITY_SCHEDULE.md) · What was tested: [docs/TEST_REPORT.md](docs/TEST_REPORT.md)

## New in v2.8

- **Smart Mode for Auto Review & Post**: a package posts by itself only when it is low risk. These always wait for you: the first 5 Pixel and first 10 Penny packages you approve (trust period), time-sensitive topics, sensitive money advice (taxes, debt, investing picks, guarantees) and any fact only partly backed by a source.
- **Money math is recalculated by code**, not judged by an AI: each number claim carries its formula; inputs must come from the sources or be stated, and a wrong result is fixed or the package waits.
- **No invented hands-on tests**: "I tested / we tried" sentences are removed from scripts, titles and posts. Pixel researches and compares from dated sources.
- **Money titles name the country** whose rules they use (for example "(US)" for a 401(k) video).
- **Repetition check**: a script or title too close to one from the last 180 days is held back.
- **YouTube categories per channel** (Pixel: Science & Technology, Penny: Education), English audio language, and the AI-content label set per video from what is in it.
- **Brand art** for both channels in `docs/brand/`; the weekly backup runs on Ubuntu 24.04 again.
- No new migration.

## New in v2.7

- **Strictly independent checks**: every company that writes or edits text (by host and by model maker) is kept away from every check: facts, critic, hook choice, idea scoring and the final publishing review. No fallback: a step waits instead.
- **Strict audit trail**: the audit log is append-only and hash-chained (`audit_chain_problems()` lists any tampering); every status change of packages, posts and schedules is recorded automatically.
- **Strictly no duplicate uploads**: an attempt is recorded before anything is sent; an unclear attempt blocks the post until you retry; the same video or text (SHA-256) can never be posted twice to one account; published posts are permanent.
- **8-14 minute videos** written from an outline (problem, what you'll learn, 3-5 teaching parts, limits, wrap-up), deepened when short, never padded.
- **Target countries** per channel (Pixel: US, UK, CA, AU, DE/NL; Penny: US, CA, UK, AU, CH/SG); off-topic trending searches no longer become ideas.
- **Launch dates** (Pixel 25 Oct, Penny 1 Nov 2026) and a smaller starting schedule timed for US viewers.
- **YouTube sign-in asks for read-only analytics and revenue reports**, ready for per-video results.
- **Migration 10** (`20261027000010_strict_audit_publishing.sql`): apply after merging (First-time setup → keys_only, or `studio migrate`).

## New in v2.6

- **Five pages**: Home, Create, Content, Calendar, Activity (Settings, Help, theme and Sign out at the bottom; **More** on a phone). Old links and platform sign-in returns redirect to the new pages.
- **Create one package from one idea** (`produce_idea` job): only the chosen idea is made, posts are planned and auto-reviewed for that package only, two presses make one package, and a failed step resumes without remaking finished work or posts. Publishing pause doesn't block it.
- **Honest readiness**: Create is blocked only by real problems (Worker, database, GitHub, no passing AI service). A key check older than 24 hours is flagged with **Test again**, and jobs no passing service covers are named.
- **Approval mode shown before Create package** and in the menu: *You approve* or *Auto Review & Post*.
- **Migration 9** (`20261026000009_produce_selected_idea.sql`): links a generated idea to its research idea once, and allows one package per idea. Apply it after merging with **Actions → First-time setup → keys_only** (or `studio migrate`); it's safe to repeat. Existing data was checked read-only: no duplicates block it.

## New in v2.5

- **Setup page**: every connection step by step with a live ✅ test; paste keys there instead of GitHub (encrypted, only the last 4 characters shown).
- **Activity page**: what's running now with progress, today's numbers, and a plain-language timeline with a fix button on every problem.
- **Posting schedule editor** (Settings): days, times, posts per week and pause per account, with a weekly preview and warnings.
- **Auto Review & Post fixes and retries**: a failed check is repaired and the package re-checked, up to 3 times (adjustable), then posted at the next free slot.
- **Clear buttons with Undo** on every history list; **Simple / Advanced** menu; first-time tour; plain labels with "?" explanations.
- **Key guidance on AI APIs**: which providers suit several keys, one key, or no borrowed keys.

## What it does each week

**Mission Control** is the operator landing page: direct a research mission, choose its channel and council depth, watch real model handoffs and failures, inspect the run queue, and check setup readiness. Open `/demo` to explore the interface with non-persistent sample data.

1. **Saturday:** collects fresh sources concurrently (news, trends, official data), several free AI models pitch ideas, and the
   ideas are scored and shortlisted.
2. **Sunday:** writes source-checked scripts with a multi-model team (writer, voice editor, critic and claim checker
   are different providers), records the hosts with Kokoro TTS, renders previews, thumbnails, Shorts and per-platform
   posts, and plans the week. You get a Telegram message.
3. **Monday:** you review and approve in the dashboard.
4. **All week:** approved posts are published through official APIs, or turned into one-tap/manual tasks where a
   platform doesn't allow it yet.

Cost: $0, except optional X posting, which is hard-capped at $1/month.

## Repository layout

| Folder | What |
|---|---|
| `engine/` | Python engine (`studio` CLI): research, AI router, script pipeline, video rendering, publishing |
| `dashboard/` | React + TypeScript + Tailwind dashboard (live on Vercel: https://dashboard-beta-ten-13.vercel.app) |
| `worker/` | Cloudflare Worker: OAuth connect, Telegram bot, owner-only dispatch, 15-minute cron |
| `supabase/migrations/` | Database schema, Row Level Security, owner actions |
| `config/` | Brand, accounts and schedule, AI providers, research sources, budgets and limits |
| `.github/workflows/` | Weekly research and production, publishing, owner-request queue, maintenance and backups, setup, benchmark, Worker deploy, tests |
| `.claude/skills/free-llm-apis/` | Skill for setting up free LLM provider keys |

## Developer quick start

```bash
python3 -m venv .venv && .venv/bin/pip install -e "engine[test]"
# tests need a local PostgreSQL (postgres/postgres on localhost) — they create a throwaway database
cd engine && ../.venv/bin/pytest -q
.venv/bin/studio demo            # renders the two channel trailers with real voices (no keys needed)
cd worker && npm ci && npx vitest run
cd dashboard && npm ci && npm test && npm run build
```
