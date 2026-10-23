# Architecture

```
                         ┌──────────────────────────── owner ─────────────────────────────┐
                         │ browser (Dashboard)                     phone (Telegram)        │
                         └───────┬───────────────────────────────────────┬────────────────┘
          anon key + session     │                                       │ bot webhook
          (RLS decides)          ▼                                       ▼
 ┌────────────────────┐   ┌──────────────┐  dispatch / OAuth / link  ┌──────────────────────┐
 │ Cloudflare Pages    │──▶│  Supabase     │◀──────────────────────────│ Cloudflare Worker     │
 │ React dashboard     │   │  Postgres+RLS │   service role (server)   │ cron */15, OAuth,     │
 └────────────────────┘   │  Auth, Storage│                            │ Telegram, dispatch    │
                          └──────▲───────┘                            └──────────┬───────────┘
                                 │ DB owner connection                          │ workflow_dispatch
                                 │                                              ▼
                          ┌──────┴──────────────────────────────────────────────────────────┐
                          │ GitHub Actions — Python engine `studio`                          │
                          │ research → ideas → scripts (multi-model) → verify → render       │
                          │ (Kokoro + FFmpeg) → package → schedule → publish (official APIs) │
                          └──────┬──────────────────────┬───────────────────────────────────┘
                                 │ free AI APIs          │ YouTube · Facebook · TikTok · X
```

## Engine modules (`engine/studio`)

| Module | Responsibility |
|---|---|
| `config.py` | YAML config + environment secrets |
| `db.py`, `jobs.py` | Postgres helpers; persistent idempotent job runner (attempts, backoff with jitter, resume) |
| `ai/router.py`, `ai/usage.py` | Free-tier router: role-based model choice, quota tracking, circuit breakers, JSON repair, fallback |
| `research/sources.py`, `research/engine.py` | Source adapters, dedupe, topic classification, brainstorming, scoring, shortlisting |
| `similarity.py` | Repetition check (embeddings if available, TF-IDF otherwise) |
| `script/models.py`, `script/pipeline.py`, `script/quality.py`, `script/verify.py` | Structured script schema, adaptive pipeline, deterministic gates, claim verification |
| `media/tts.py`, `media/visuals.py`, `media/captions.py`, `media/render.py`, `media/thumbnails.py`, `media/stock.py` | Narration, on-brand cards and charts, word-timed captions, scene-cached rendering from recipes, thumbnails, licensed photos |
| `produce.py` | Config sync, Saturday and Sunday batches, distribution plan |
| `capacity.py` | Free-capacity planner (GitHub minutes, storage, AI requests) |
| `publish/adapters.py`, `publish/runner.py` | Platform adapters with capability detection; safe publish runner |
| `oauth.py` | AES-GCM token storage (shared format with the Worker), token refresh and health |
| `budget.py` | X spend reservation, commit and release |
| `maintenance.py` | Owner-requested jobs, retention cleanup, freshness expiry |
| `notify.py` | Deduplicated Telegram notifications |
| `cli.py` | `studio migrate / init / research / produce / publish / queue / maintain / demo / benchmark / capacity / providers / status` |

## Data flow and states

`content_ideas` → `content_projects` (long + child shorts) → `script_versions` (immutable) + `scenes` +
`research_claims` → `media_assets` / `thumbnails` → `content_variants` (one per account and kind) →
`scheduled_posts` (`pending_approval` → `scheduled` via approval trigger → `publishing` → `published` |
`needs_manual` | `needs_review` | `blocked` | `failed`) → `published_posts` (unique per scheduled post).

## Why the final video is rendered at publish time

Storing six 1080p masters a week would overflow free storage. Each project keeps a small **recipe**; the publish job
re-renders the final from it (scene cache makes this fast) and keeps the master as a 14-day GitHub artifact.
