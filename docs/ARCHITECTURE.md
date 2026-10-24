# Architecture

```
                         ┌──────────────────────────── owner ─────────────────────────────┐
                         │ browser (Dashboard)                     phone (Telegram)        │
                         └───────┬───────────────────────────────────────┬────────────────┘
          anon key + session     │                                       │ bot webhook
          (RLS decides)          ▼                                       ▼
 ┌────────────────────┐   ┌──────────────┐  dispatch / OAuth / link  ┌──────────────────────┐
 │ Vercel (dashboard)  │──▶│  Supabase     │◀──────────────────────────│ Cloudflare Worker     │
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
| `config.py`, `secrets.py` | YAML config + environment secrets; values saved on the dashboard Setup page (encrypted `app_secrets`) loaded into the environment at connect time, winning over GitHub secrets |
| `db.py`, `jobs.py` | Postgres helpers; persistent idempotent job runner (attempts, backoff with jitter, resume); context-local model-call attribution; live job progress and tracked weekly runs for the Activity page |
| `ai/router.py`, `ai/usage.py`, `ai/credentials.py`, `ai/catalog.py` | Router: role-based model choice, several keys per provider (5 strategies, caps, quota groups, health), bounded jittered retries, circuit breakers, parallel limits, JSON repair, provider fallback with substitution notes, live model catalog |
| `research/sources.py`, `research/engine.py` | Bounded-concurrent source adapters, per-source failure isolation, main-thread database writes, dedupe, topic classification, owner-directed multi-model brainstorming, scoring, shortlisting |
| `review/auto.py` | Auto Review & Post (default OFF): deterministic checks + independent AI policy review, transactional auto-approval, fix-and-retry of failed checks (inline post fixes or rewrite/recheck/re-render jobs, bounded attempts), missed slots moved to the next free one, Telegram on every outcome |
| `ideas/generator.py` | AI Idea Generator: evidence pool, cited proposals, measured 70% trend score, independent assessment, dedupe, diversity, refine |
| `similarity.py` | Repetition check (embeddings if available, TF-IDF otherwise) |
| `script/models.py`, `script/pipeline.py`, `script/quality.py`, `script/verify.py` | Structured script schema, adaptive pipeline, deterministic gates, claim verification |
| `media/tts.py`, `media/visuals.py`, `media/captions.py`, `media/render.py`, `media/thumbnails.py`, `media/stock.py` | Narration, on-brand cards and charts, word-timed captions, scene-cached rendering from recipes, thumbnails, licensed photos |
| `produce.py` | Config sync, Saturday and Sunday batches, distribution plan |
| `capacity.py` | Free-capacity planner (GitHub minutes, storage, AI requests) |
| `publish/adapters.py`, `publish/runner.py` | Platform adapters with capability detection; safe publish runner |
| `oauth.py` | AES-GCM token storage (shared format with the Worker), token refresh and health |
| `budget.py` | X spend reservation, commit and release |
| `maintenance.py` | Owner-requested jobs (follow-up fix rounds in the same run), retention cleanup, freshness expiry |
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
