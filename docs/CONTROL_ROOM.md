# Mission Control

Mission Control is the dashboard's operator landing page. It exposes actual engine telemetry rather than inventing autonomous activity.

## What the owner can do

- Write an objective of up to 2,000 characters for the research council.
- Scope a mission to Pixel AI, Penny Money, or both channels.
- Choose 2, 3, or 5 independent brainstorming providers.
- Stop after research and ideas, or continue to a review package.
- Watch provider calls, latency, token use, failures, handoffs, and recent jobs.
- Pause automatic feed refreshes, filter activity by stage, refresh manually, and cancel queued jobs.
- Start the existing research, production, and approved-and-due publishing workflows.
- See whether models, social accounts, instant Worker dispatch, and publishing guards are ready.

A research-plus-production mission ends at `ready_for_review` or `needs_attention`. It does not approve content or start publication. Existing claim checks, freshness checks, budget limits, owner-only access, and platform-specific manual fallbacks remain authoritative.

## Live data

The page reads only owner-accessible Supabase rows:

- `provider_usage`: real model calls, role, job attribution, success, latency, and token counts.
- `generation_jobs`: queued, running, completed, retrying, and failed work.
- `ai_providers` and `ai_model_configs`: enabled routing and provider health.
- `social_accounts` and `oauth_connections`: connection readiness.

Migration `20261024000005_control_room.sql` adds indexes for these activity views. Apply it through the normal `studio migrate` setup/deployment path before using the upgraded dashboard against an existing project.

## Engine behavior

Independent source adapters fetch concurrently, bounded by `parallel_sources` in `config/research.yaml` (default 6). A failed adapter is reported without cancelling other sources. Database writes remain on the calling thread; psycopg connections are never shared with fetch workers.

`job_context` uses context-local state to associate model usage with the active generation job. Nested stages restore the previous context on exit.

Single-channel missions scope research, production, distribution planning, readiness summaries, and notifications to that channel. The default weekly behavior still covers both channels.

## Safety and design notes

- **No overlapping runs.** Research and production each take a database advisory lock (`db.run_lock`). A mission
  that starts while the Saturday or Sunday batch is running returns `skipped` instead of producing the same ideas
  twice or spending the free AI quota twice. Different kinds (research vs production) don't block each other.
- **Long missions fit.** *Owner requests* runs up to 330 minutes, so a "Research + review package" mission (full
  production, 1-3 hours) is not cut off.
- **Theme.** Mission Control uses `--cr-*` colour tokens with light and dark values, so it follows the same
  light/dark setting as the rest of the dashboard.
- **Light page loads.** Every page is loaded on first visit (`React.lazy`), so Mission Control does not make the
  sign-in screen or other pages heavier.

## Demo

`/demo` is a public, explicitly labelled interface evaluation with sample data. It does not call AI providers or social accounts and does not save changes. Launching a demo mission only adds a local sample event. The production `/` route always requires the normal Supabase configuration and owner sign-in.

The demo is linked from the unconfigured setup screen and the sign-in screen. It is not a substitute for connecting Supabase, applying migrations, configuring provider keys, or linking social accounts.
