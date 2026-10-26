# Reliability audit checklist

The owner asked for this review (26 Oct 2026). Every page, shared component, job type, background workflow and
notification event is listed below. Each one is marked as one of:

- **verified**: checked, and it behaves correctly.
- **fixed**: a confirmed defect was corrected (the phase and PR are named).
- **unaffected**: outside this phase's concern.
- **blocked**: it can't be checked here, with the reason.
- **open**: not reviewed yet.

The status is updated phase by phase. Findings that are improvements rather than defects are labelled as such.

## Phase summary

| Phase | Scope | Branch | Status |
|---|---|---|---|
| 1 | Trustworthy state, authentication, errors | `audit/phase-1-state` | done (PR open, not merged) |
| 2 | Durable drafts and unfinished-project recovery | `audit/phase-2-drafts` | open |
| 3 | Direct navigation and discoverable work | `audit/phase-3-navigation` | open |
| 4 | Settings reliability | `audit/phase-4-settings` | open |
| 5 | Job lifecycle, recovery and cancellation | `audit/phase-5-jobs` | open |
| 6 | Review, scheduling, publishing and Undo | `audit/phase-6-publishing` | open |
| 7 | Reliable Telegram delivery | `audit/phase-7-telegram` | open |
| 8 | Full acceptance review | `audit/phase-8-acceptance` | open |

## Pages

| Page | Route | Phase 1 | Notes |
|---|---|---|---|
| Sign-in / access gate | (all) | fixed | A failed access check showed "already has an owner": now "Couldn't check your access" with Retry and Sign out. The page you were going to (with query and anchor) is kept through sign-in and session expiry. Sign-in can't be double-submitted and keeps the email. |
| Home | `/` | fixed | "Nothing needs you", "Nothing is being made", "No posts planned", "keys haven't been checked" and "no AI service covers these jobs" were shown when the data failed to load. Each now says it couldn't load, with Retry. The Pause button is offered only once the current state is confirmed. |
| Create | `/create` | fixed | Ideas and sources show a failure instead of "none"; duplicate error note removed; Retry added. |
| Content | `/content` | fixed | The same error was shown twice; now once, with Retry. |
| Ideas | `/content/ideas` | fixed | Ideas, research and runs show a failure instead of "none"; Pick and Skip can't be double-clicked. |
| Project (Review) | `/content/:id` | fixed | A failed load had no way to try again: Retry added. Approve buttons are disabled while saving. |
| Calendar | `/calendar` | fixed | Duplicate error note removed; recheck reports whether it starts now or on the next queue run; Retry can't be double-clicked. |
| Activity | `/activity` | fixed | "Nothing is running" and an empty timeline were shown on a failed load; now a failure with Retry. |
| Settings: Getting started (Setup) | `/settings/setup` | fixed | The page crashed when the Worker returned an unexpected answer; "0 of 6 steps done" was shown when checks failed (now "At least N of 6… some checks didn't answer"); Telegram step shows a failed check instead of "not linked". |
| Settings: Accounts | `/settings/accounts` | fixed | A failed load shows a failure instead of no accounts. |
| Settings: Posting schedule | `/settings/schedule` | verified | Checked with every request failing (desktop and phone); save reliability is Phase 4. |
| Settings: Automation | `/settings/automation` | fixed | "No automatic reviews yet" on a failed load; Auto Review & Post switch said OFF when its state was unknown (now "unknown" and disabled). A failed pause save leaves the state unchanged and shows one message. |
| Settings: Ideas & research | `/settings/ideas` | fixed | Recent idea runs show a failure instead of "None yet". |
| Settings: AI services & keys | `/settings/ai` | fixed | "Not checked yet" and zero totals were shown on a failed load; now "Couldn't load the last check" and "—". Retry added to the writers and API Manager notes. |
| Settings: Channel voices | `/settings/voices` | fixed | A failed load shows a failure instead of no channels. |
| Settings: Notifications | `/settings/notifications` | fixed | Telegram showed "not linked" when the check failed. |
| Settings: Budget | `/settings/budget` | verified | Checked with every request failing (desktop and phone); budget errors are Phase 4. |
| Settings: Appearance & region | `/settings/appearance` | verified | Checked with every request failing (desktop and phone). |
| Help | `/help` | verified | Static; updated in Phase 8. |
| Demo (Mission Control sample) | `/demo` | unaffected | Sample data only, never reads the studio. |
| Legal | `/privacy`, `/terms` | unaffected | Static pages. |
| Old addresses | `/week`, `/review/:id`, `/settings?connected=…`, … | verified | Browser test: `/settings?connected=youtube` keeps its query; `/review/:id` goes to `/content/:id`. |

## Shared components and libraries

| Item | Phase 1 | Notes |
|---|---|---|
| `AuthGate` | fixed | See Sign-in above. |
| `Layout` (sidebar, phone menu, status chips) | fixed | Offline banner; "paused" only when confirmed, a failed check says so with Retry; other tabs' changes refresh this tab; Sign out is deliberate (not reported as an expired session). |
| `RunningNow` | fixed | Said "Studio idle" when the job list failed to load; now "Couldn't check what's running". |
| `AutoPostToggle` / `AutoPostBadge` / `ApprovalModeNotice` | fixed | Read a failed load as OFF ("You approve"); now "checking…" / "couldn't check" and the switch is disabled until known. |
| `ClearButton` / `lib/clear` | unaffected | Clear scope is Phase 5. |
| `ui` (Confirm, Toast, ErrorNote, Loading, Empty) | fixed | New `NotConfirmed` (loading / failed with last-known time / offline); `ErrorNote` has Retry; plain-language errors; one toast per failure (a specific message replaces the general one); toasts announced to screen readers; a failing Undo can't crash the page. |
| `Tour` | fixed | Opened the tour when the "tour done" setting failed to load. |
| `PostingSchedule` | unaffected | Phase 4. |
| `IdeaGeneratorPanel`, `IdeaCard`, `ResearchIdeaCard` | fixed | Retry on the error note; Pick / Skip can't be double-clicked. |
| `Rundown` | verified | Covered by the Home sweep. |
| `lib/api` (`must`, `useSetting`, `useSaveSetting`, `queueJob`) | fixed | Network failures become plain errors; `queueJob` reports whether work starts now or on the next queue run; saves tell other tabs. |
| `lib/supabase` (`callWorker`, `signedUrl`) | fixed | `callWorker` explains an unreachable Worker and an expired sign-in (401) instead of a raw error. |
| `lib/readiness`, `lib/activity`, `lib/content`, `lib/schedule`, `lib/routes` | fixed | `readiness` separates "couldn't load" from "never checked" / "nothing covers this" (unit-tested). Others unaffected. |

## Job types

| Job | Runs in | Phase 5 | Notes |
|---|---|---|---|
| `produce_idea` | queue | open | |
| `script`, `package`, `render_preview`, `thumbnails`, `project` (stages) | inside production | open | |
| `regenerate_script`, `rerender_preview`, `regenerate_thumbnails`, `recheck_project` | queue | open | |
| `run_research`, `run_production`, `run_mission` | queue | open | |
| `generate_ideas`, `refine_idea` | queue | open | |
| `auto_review` | queue | open | |
| `check_providers` | queue | open | |
| `weekly_research`, `weekly_production` (tracked runs) | scheduled | open | |

## Background workflows

| Workflow | Trigger | Status | Notes |
|---|---|---|---|
| `queue.yml` (Owner requests) | Worker dispatch / 15-minute cron | open | |
| `weekly-research.yml` | Saturday | open | |
| `weekly-produce.yml` | Sunday | open | |
| `publish.yml` | Worker cron when posts are due | open | |
| `maintenance.yml` | nightly | open | |
| `setup.yml` (First-time setup) | manual | open | |
| `deploy-worker.yml`, `ci.yml`, `benchmark.yml` | push / manual | open | |
| Worker cron (`handleCron`) | every 15 minutes | open | |

## Notification events

| Event | Source | Phase 7 | Notes |
|---|---|---|---|
| `ideas_ready` | engine (ideas) | open | |
| `package_ready`, `week_ready` | engine (production) | open | |
| `auto_approved`, `auto_fixing`, `auto_review_needs_you` | engine (auto review) | open | |
| `held_reminder`, `auto_replace` | engine (replacement) | open | |
| `published`, `publish_blocked`, `publish_ambiguous`, `manual_task` | engine (publishing) | open | |
| `job_failed` | engine (queue) | open | |
| `expired`, `token` | engine (maintenance) | open | |
| `ai_model_retired`, `ai_model_back`, `ai_model_given_up`, `ai_key_rejected` | engine (AI health) | open | |
| Auto Review & Post on/off, pause/resume | Worker (dashboard + Telegram) | open | |
| Telegram commands (`/status`, `/week`, `/review`, `/failed`, `/budget`, `/pause`, `/resume`, `/autopost`) | Worker | open | |

## Phase 1 evidence

- Unit tests: `cd dashboard && npx vitest run` (52 pass), including `lib/state.test.ts` and the readiness cases.
- Browser checks against a **simulated** database and Worker (nothing reaches the live studio):
  `cd dashboard && node e2e/phase1.mjs` (11 scenarios: normal load on desktop and phone, failed access check + Retry,
  confirmed non-owner, failed settings, failed lists, offline + reconnect, signed out, expired sign-in that can't
  refresh, failed save, change in another tab, old addresses / OAuth return). Screenshots: `dashboard/e2e/screenshots/phase1/`.
- Every page with every request and the Worker failing, desktop and phone: `node e2e/sweep.mjs` (no crash, no
  "nothing here" / "all fine" wording). Screenshots are written to `dashboard/e2e/screenshots/sweep/` (not committed).
- Playwright isn't a dashboard dependency: the scripts use the copy installed on the machine
  (`NODE_PATH=$(npm root -g)` or wherever `require.resolve("playwright")` finds it).

Remaining limitations (Phase 1): a sign-in link opened in another browser can't know where you were (it opens Home);
the "last known" time is shown only for data this tab loaded before the failure; the demo page is unchanged.
No migration is needed for Phase 1.
