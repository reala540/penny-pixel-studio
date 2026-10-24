# Penny & Pixel Studio — AI Content Studio v2.5

A free-first, mostly automated content studio for two faceless YouTube channels (**Penny & Pixel AI** with host
Pixel, **Penny & Pixel Money** with host Penny), a Facebook Page, TikTok and X.

- **New here?** Read **[GUIDE.md](GUIDE.md)**: step-by-step setup, written for non-coders.
- Specification: [docs/SPEC_v2.1.md](docs/SPEC_v2.1.md) · Architecture: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) ·
  Providers and free limits: [docs/PROVIDERS_AND_LIMITS.md](docs/PROVIDERS_AND_LIMITS.md) ·
  Mission Control: [docs/CONTROL_ROOM.md](docs/CONTROL_ROOM.md) · Ideas, themes and API keys: [docs/IDEAS_AND_API_KEYS.md](docs/IDEAS_AND_API_KEYS.md) · Auto Review & Post: [docs/AUTO_REVIEW_AND_POST.md](docs/AUTO_REVIEW_AND_POST.md) · Setup, Activity and schedule: [docs/SETUP_ACTIVITY_SCHEDULE.md](docs/SETUP_ACTIVITY_SCHEDULE.md) · What was tested: [docs/TEST_REPORT.md](docs/TEST_REPORT.md)

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
