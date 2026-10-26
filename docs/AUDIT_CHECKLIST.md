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
| 1 | Trustworthy state, authentication, errors | `audit/phase-1-state` | merged; reliability follow-up documented below |
| 2 | Durable drafts and unfinished-project recovery | `audit/phase-2-drafts` | merged; reliability follow-up documented below |
| 3 | Direct navigation and discoverable work | `audit/fixes-phases-3-8` (with fce9fe2) | done (PR open, not merged); see "Audit 26 Oct" |
| 4 | Settings reliability | `audit/fixes-phases-3-8` (with fce9fe2) | done (PR open, not merged); see "Audit 26 Oct" |
| 5 | Job lifecycle, recovery and cancellation | `audit/fixes-phases-3-8` (with fce9fe2) | done (PR open, not merged); see "Audit 26 Oct" |
| 6 | Review, scheduling, publishing and Undo | `audit/fixes-phases-3-8` (with fce9fe2) | done (PR open, not merged); see "Audit 26 Oct" |
| 7 | Reliable Telegram delivery | `audit/fixes-phases-3-8` (with fce9fe2) | done (PR open, not merged); see "Audit 26 Oct" |
| 8 | Full acceptance review | `audit/fixes-phases-3-8` (with fce9fe2) | done (PR open, not merged); see "Audit 26 Oct" |

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
| `produce_idea` | queue | fixed | Resumes finished steps; one job per idea across tabs/devices; an automatic retry keeps remaining attempts (`fresh_attempts=False`), Try again gives fresh ones. Tests: test_produce_idea, test_audit_fixes. |
| `script`, `package`, `render_preview`, `thumbnails`, `project` (stages) | inside production | fixed | "Retry scheduled" steps had no runner (`due_jobs` was never called): `resume_due_retries` now runs them on each queue run, bounded by `max_attempts`, never for decided packages or while the owner has a request on it; the owner is told once when retries end. |
| `regenerate_script`, `rerender_preview`, `regenerate_thumbnails`, `recheck_project` | queue | verified | Queued only by owner clicks (now also "Rebuild the preview" when its file was removed). A new script version withdraws an approval (migration 14). |
| `run_research`, `run_production`, `run_mission` | queue | fixed | Research results link to exactly what that request found (`?since=`). |
| `generate_ideas`, `refine_idea` | queue | fixed | Results link to that run's ideas (`?run=`). |
| `auto_review` | queue | fixed | Won't approve a script that changed during the review (version checked under lock). |
| `check_providers` | queue | verified | Tracked by job id (`/settings/ai?job=`); deduplicated; alert links to the exact test. |
| `weekly_research`, `weekly_production` (tracked runs) | scheduled | verified | Engine tests; never reset as abandoned. Live runs not triggered (cost). |

## Background workflows

| Workflow | Trigger | Status | Notes |
|---|---|---|---|
| `queue.yml` (Owner requests) | Worker dispatch / 15-minute cron | fixed | Also runs due step retries. |
| `weekly-research.yml` | Saturday | unaffected | Not run live (would spend AI tokens). |
| `weekly-produce.yml` | Sunday | unaffected | Not run live (would spend AI tokens). |
| `publish.yml` | Worker cron when posts are due | fixed | Publisher refuses a package that isn't approved or whose script changed after approval. Not run live (would publish). |
| `maintenance.yml` | nightly | verified | Delivery retries skip safely before migration 13 (column check). |
| `setup.yml` (First-time setup) | manual | unaffected | Applies migrations 13 and 14 when the owner runs it. |
| `deploy-worker.yml`, `ci.yml`, `benchmark.yml` | push / manual | verified | CI green on fce9fe2; Worker deploy succeeded for fce9fe2. |
| Worker cron (`handleCron`) | every 15 minutes | fixed | Wakes the queue when a step retry is due (Worker test). |

## Notification events

| Event | Source | Phase 7 | Notes |
|---|---|---|---|
| `ideas_ready` | engine (ideas) | fixed | Links to that run's ideas. Routine. |
| `package_ready`, `week_ready` | engine (production) | fixed | Link to the package / Needs you (no old `/review` links). Body says when something needs a look. Always sent. |
| `auto_approved`, `auto_fixing`, `auto_review_needs_you` | engine (auto review) | verified | needs-you always sent; approved/fixing are routine. |
| `held_reminder`, `auto_replace` | engine (replacement) | verified | Reminder always sent; replacement outcomes routine. |
| `published`, `publish_blocked`, `publish_ambiguous`, `manual_task` | engine (publishing) | fixed | Blocked/ambiguous/manual now link to the exact post; a failed post says "Post failed" with the next action. `published` links to the live post (routine). |
| `job_failed` | engine (queue) | fixed | Exact request link; identical repeats within 30 minutes are sent once (all kept in the app); "Stopped retrying" when automatic retries end. |
| `expired`, `token` | engine (maintenance) | fixed | Link to the package / Settings → Accounts. |
| `ai_model_retired`, `ai_model_back`, `ai_model_given_up`, `ai_key_rejected` | engine (AI health) | verified | Grouped already (one notice per check); key rejected grouped as a repeat. |
| Auto Review & Post on/off, pause/resume | Worker (dashboard + Telegram) | verified | Worker tests (Telegram acknowledgement checked); dashboard pause alert needs migration 13. |
| Telegram commands (`/status`, `/week`, `/review`, `/failed`, `/budget`, `/pause`, `/resume`, `/autopost`) | Worker | verified | Worker tests (55); no message sent to the owner's Telegram. |

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

## Phase 2: drafts and unfinished work

| Item | Phase 2 | Notes |
|---|---|---|
| Create (`/create`) | fixed | Leaving the page lost the chosen channel, idea and typed idea: every step and the typed idea are now kept as a draft on this device ("Saved on this device"), also saved at once when the tab closes. Opening Create offers **Continue where you left off** for each draft, plus **Start new** (the old draft is kept). |
| Home (`/`) | fixed | **Unfinished** lists drafts with Continue / View progress / Fix problem and Remove (with Undo). A failed package in Needs you without a project now has **Fix problem** (its progress page with Try again) instead of no link. |
| Drafts: owner, privacy | verified | Stored per signed-in account; known fields only; text that looks like a key, token or password is never written; at most 10 drafts, 30 days. Browser test: another account doesn't see them. |
| Drafts vs the database | fixed | Each draft is checked against the database before it's offered: idea deleted → "no longer exists", Continue goes back to choosing an idea; package being made → View progress; failed → Fix problem; made → leaves the list (it's in Content). If the check fails, the draft says it couldn't check. |
| Version conflicts | fixed | The same draft changed in two tabs: the second save asks which version to keep (newer one / this one) instead of silently overwriting. |
| Continue never starts work | verified | Browser test: continuing a draft, a failed package or a deleted idea queues no job. Nothing starts until **Create package** or **Try again** is pressed. |
| Duplicate packages | fixed | **Create package** and **Try again** re-check the database right before queuing; a second tab updates itself, a second device gets "already being made". Browser test: two tabs + another device → one job. The engine also resumes, never duplicates (one package per idea; finished steps kept). |
| `produce_idea` job | verified | Engine behaviour unchanged: re-running resumes from the step that failed. |

Evidence: `node e2e/phase2.mjs` (8 scenarios, desktop and phone), screenshots in `dashboard/e2e/screenshots/phase2/`;
unit tests `src/lib/drafts.test.ts` (13). Phase 1 checks and the all-failing sweep still pass.

Remaining limitations (Phase 2): drafts live on the device where they were made (a package that was actually started
is visible everywhere, because that's in the database); private browsing may not keep drafts (the page says
"Couldn't save on this device"). No migration is needed.


## Reliability follow-up after PR #13

See [RELIABILITY_RELEASE.md](RELIABILITY_RELEASE.md) for the current implementation, migration order,
validation, and live-system limitations. The historical per-phase notes above describe those original PRs,
not a certification of the production installation.

| Area | Current evidence |
|---|---|
| Unknown states and Settings errors | Fixed and browser-tested, including editable-default and timezone failures missed by the first sweep |
| Draft recovery | Local recovery retained; owner-only cloud revision storage and cross-device browser recovery added |
| Direct destinations | Home, sidebar, Activity, AI-test detail, and cross-week Calendar links covered |
| Settings saves | Atomic patches, revision checks, non-secret edit recovery, truthful errors and refreshes |
| Job lifecycle | Single claim, active enqueue identity, scoped cooperative cancellation, and explicit checkpoint resume tested |
| Review / scheduling / Undo | Partial bulk outcomes, schedule guards/confirmation, isolated conditional Undo, and pagination implemented |
| Telegram | Durable bounded delivery retries and acknowledgement checks; local/mock tests only |
| Acceptance | Unit/build/database and simulated-browser checks completed; live connectors/deployment verification blocked |

The earlier "open" phases are superseded for the implemented items by this evidence. Live deployment,
production migration, real provider access, OAuth, social publication, and real Telegram delivery are not
certified by local tests. No production data was changed during this implementation.

## Audit 26 Oct (live check, fixes, Phases 3–8)

Live state checked read-only on 26 Oct: Vercel production and the Worker run `fce9fe2`; the database is on
migration 12 (migration 13 not applied). Everything below is on branch `audit/fixes-phases-3-8`; nothing was merged,
deployed or applied to the live database.

| Area | Status | What and evidence |
|---|---|---|
| Stop & clear permission | **fixed (critical)** | Any signed-in account could run it (guard used `current_user`, always the function owner). Migration 14: only the Worker's service role and the engine; signed-in users can't call it. Proven live in a rolled-back transaction; test_audit_fixes. |
| Version-exact approval | **fixed (high)** | `approve_project` approved whatever was current. Now requires the reviewed version; dashboard sends it (falls back to a browser-side version check before migration 14); auto-review checks it under lock; nothing recorded for ineligible packages. Tests: test_audit_fixes, e2e/audit.mjs. |
| Approval after a script change | **fixed (high)** | Editing an approved package's script now withdraws the approval (posts back to waiting), audited; published script/text can't be changed; the publisher refuses a package that isn't approved or changed after approval. |
| Scheduling rules on every path | **fixed (high)** | Past times and 30-minute clashes are refused for owner changes made directly on the table too (trigger), and in the browser before migration 13. |
| Table privileges | fixed (low) | TRUNCATE/TRIGGER/REFERENCES removed from `anon`/`authenticated`. |
| Cloud drafts before migration 13 | fixed (medium) | No misleading page-wide banner or 15-second polling of a missing table; drafts say they're on this device only. |
| Account switch / sign-out | fixed (medium) | Cached data cleared; the owner answer is tied to the account it was checked for. |
| Phase 3 links | fixed | Shared engine link builder (`studio/links.py`, mirrors `jobDestination`); exact post/test/run/request links; Ideas and Content filters and page kept in the address; today's counts link to their lists; deleted destinations explained (verified). No nested controls on any page (sweep). |
| Phase 4 settings | fixed | Keys are tested straight after saving ("Saved, but the connection test failed: …"); removal explains the fallback; schedule moves preview how many posts move and explain timezone effects; failed counts never show 0. Voice and idea settings verified consumed by the engine and kept by config sync. |
| Phase 5 jobs | fixed | Plain states (waiting, interrupted, stopping, retry scheduled, waiting for quota, cancelled); retry runner (above); Cancel work and Clear draft on the progress page; Stop & clear text states its scope and what can't be recalled. |
| Phase 6 media | fixed | A removed file is told apart from a failed request; "Rebuild the preview" only on click. Caption edits of approved posts stay allowed (owner decision); published post text is locked. |
| Phase 7 Telegram | fixed | Keys/tokens/passwords scrubbed before storing or sending; "Only what needs me" preference (routine updates stay in the app); identical repeats grouped; undelivered alerts listed with the reason; unconfigured ≠ failed. Simulated Telegram only (test_alerts). Exactly-once delivery is not claimed. |
| Phase 8 acceptance | verified (simulated) | Unit, database, Worker and browser suites (desktop and phone) with seeded data and simulated services; Help and tour updated. Live sign-in, OAuth, publishing and real Telegram delivery were not exercised (would act on live data). |

Not verifiable from here: Supabase Auth settings (sign-ups, Site URL, redirect list, email confirmation), live
end-to-end flows, real Telegram delivery. Branch deletion on GitHub is blocked for this session (all branches are
already in main).
