# Penny & Pixel Studio — AI Content Studio v2.1

A free-first, mostly automated content studio for two faceless YouTube channels (**Penny & Pixel AI** with host
Pixel, **Penny & Pixel Money** with host Penny), a Facebook Page, TikTok and X.

- **New here?** Read **[GUIDE.md](GUIDE.md)**: step-by-step setup, written for non-coders.
- Specification: [docs/SPEC_v2.1.md](docs/SPEC_v2.1.md) · Architecture: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) ·
  Providers and free limits: [docs/PROVIDERS_AND_LIMITS.md](docs/PROVIDERS_AND_LIMITS.md) ·
  What was tested: [docs/TEST_REPORT.md](docs/TEST_REPORT.md)

## What it does each week

1. **Saturday:** collects fresh sources (news, trends, official data), several free AI models pitch ideas, and the
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
