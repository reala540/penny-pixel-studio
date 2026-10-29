# Reliability release

This release builds on merged PRs #12 and #13. It preserves manual/automatic approval rules, provider independence,
platform publishing safeguards, immutable records, and budgets. It does not publish posts or alter live configuration.

## Changes

- Confirmed/unknown Settings states: no manual-approval reassurance when the mode is unknown, no editable defaults
  after failed idea/automation reads, no blank schedule failures, and no unconfirmed timezone presented as saved.
- Non-secret recovery copies for script/post, voice, schedule, budget, and idea-settings text edits. Conflicting
  server changes are surfaced rather than overwritten. Credential forms never use recovery storage.
- Creation bookmarks retain their device copy and additionally sync to owner-only cloud storage. Cloud revisions
  reject stale writes; concurrent edits are preserved as separate recovered copies. A removal that conflicts with
  another device's edit restores that draft for review. Removing a bookmark does not delete content.
- Shared destinations for running cards, the sidebar, and timeline events. AI-test links include the selected test.
  Requests without projects have an Activity detail view. Opening any link is read-only.
- Calendar links fetch their post independently of the displayed week. Server rescheduling checks the account,
  mutable status, future time, and 30-minute clash; local clock-change gaps are rejected by the editor.
- Partial bulk approvals list successful and unsuccessful packages separately. Content/Ideas have pagination;
  the new Activity RPC pages one ordered union rather than truncating separate event sources.
- Atomic Settings patches preserve unrelated fields. Clear/Undo changes only its own list and refuses to undo
  over a newer clear. Unresolved failures and delivery warnings remain visible after clearing history.
- Schedule reset preserves Posting/Paused. Moving existing posts requires confirmation. Stale schedule/voice/model
  role saves are refused. Provider controls and readiness caches refresh together; old failed key checks warn
  rather than permanently block creation. AI-test completion refreshes results.
- Queue identity deduplicates active identical owner requests. Jobs are claimed one at a time. Individual cancellation
  is cooperative, preserves completed content, and does not cancel unrelated work or scheduled publication.
  Cancelled stages can be explicitly resumed. Abandoned jobs require six hours without progress, longer than the
  longest configured 330-minute owner workflow; recently progressing jobs are not reset.
- Follow-up automatic review is restricted to the completed request's projects. Explicit global auto-review and
  weekly batch behavior remain unchanged.
- Telegram event deduplication is separate from delivery. The engine claims a short delivery lease, honors backoff,
  retries up to five attempts, leaves historical unsent alerts unqueued during upgrade, and records failed/unconfirmed delivery without storing request URLs or tokens.
  The Worker dispatches delivery work when appropriate. Rejected approval-mode alerts enter the outbox. Test,
  research, cancellation, and dashboard pause events have durable alerts. Existing production/publishing alerts
  continue through the same sender. The Worker now checks Telegram's actual acknowledgement.
- Global Stop & clear remains a separate destructive operation. Cancellation acceptance is not described as proof
  that an external request has already stopped; already-finished GitHub runs are not counted as cancellation requests.

## Audit fixes (migration 14) — 26 Oct

Live check: the dashboard and Worker run `fce9fe2`, the database is still on migration 12. Migration 14
(`20261031000014_audit_fixes.sql`) is independent of 13 and was tested applying both before and after it:

- Stop & clear can no longer be run by any signed-in account (critical: its guard used `current_user`).
- Approval is tied to the reviewed script version; a new script withdraws an approval; published text is locked.
- Owner scheduling rules (future time, 30-minute clash) hold on direct table changes too.
- TRUNCATE/TRIGGER/REFERENCES removed from the API roles.

Until migration 14 is applied the new dashboard checks the version itself before using the older approval function,
and rejects past/clashing times in the browser. The database guarantees need the migration.

## Required database rollout

**Production schema/application state has not been inspected through Vercel/Supabase connectors: those tools were
not available in this session. Do not infer that pushing code applied a migration or verified a deployment.**

1. Back up the database using the normal Supabase process. Confirm migrations 1–12 are recorded in
   `studio_meta.migrations`. If not, inspect the discrepancy rather than guessing which SQL has run.
2. Apply `supabase/migrations/20261030000013_reliability.sql` and then `20261031000014_audit_fixes.sql`, each in
   one transaction, using the normal `studio migrate` mechanism (or First-time setup) when its migration ledger is correct. It adds columns, a draft table, and owner-only functions;
   it does not delete projects, alter existing credentials, or change approval defaults.
3. Refresh PostgREST's schema cache if the new functions are not discovered after application:
   `NOTIFY pgrst, 'reload schema';`.
4. Verify the owner can use the functions and a different authenticated user/anonymous user cannot. The same
   permission checks, cloud-draft revision conflicts, schedule clashes, and Activity paging run in local tests.
5. Confirm the Vercel dashboard and Cloudflare Worker deploy the intended commit. A push may trigger configured
   deployment integrations; that is not proof of their outcome.
6. In an authorized owner session, inspect Home, Create recovery, Settings, and a Calendar deep link. Do not create
   live content or publish merely to validate navigation. Any deliberate live Telegram test should be agreed with
   the owner and clearly labeled.

Before migration 13, normal enqueue, Settings patches, and schedule saves retain compatible fallback behavior only
when PostgREST explicitly reports a missing new function. Cloud sync and per-request cancellation explain that
an update is needed. Existing device recovery and generation remain usable. The stronger database guarantees,
cloud recovery, and delivery retries require the migration; they must not be claimed active before it is applied.

## Validation evidence

- Full engine suite: **159 passed** with local PostgreSQL, all migrations present at that run, real FFmpeg rendering,
  mocked AI/platform services. Subsequent additive SQL and cancellation-resume changes received targeted reruns.
- Final database/production target: **31 passed** covering migration functions, owner isolation, revision conflicts,
  scheduling, selected-idea production, and cancelled-stage resume. Final focused follow-up: **25 passed**. These runs overlap and should not be added as unique test counts.
- Dashboard: **69 unit tests**, TypeScript check, production build. Worker: **54 unit tests** and TypeScript check.
- Existing simulated-browser suites: **11 Phase 1** and **8 Phase 2** scenarios passed.
- New simulated-browser regressions: **9 scenarios** covering Settings failures, task links, cross-device recovery,
  cross-week Calendar links, partial bulk approval, and scoped cancellation.
- Failed-service sweep: **36 desktop/phone page views**; no crashes or the checked false-empty/healthy claims.

Browser tests use simulated Supabase/Worker services and no real Telegram recipients. Database tests use throwaway
local databases. These results do not verify live provider availability, social OAuth, actual publication, or live
Telegram delivery. They are not a guarantee that no undiscovered defects remain.

Reproduce:

```sh
cd dashboard
npm ci
npm run typecheck
npm test
npm run build
# Playwright must be installed; optionally set PLAYWRIGHT_CHROMIUM_EXECUTABLE to a system Chromium.
# E2E_SCREENSHOT_DIR can point outside the checkout to avoid changing committed evidence images.
node e2e/phase1.mjs
node e2e/phase2.mjs
node e2e/reliability.mjs
node e2e/sweep.mjs
cd ../worker
npm ci
npm run typecheck
npm test
cd ../engine
# STUDIO_TEST_ADMIN_URL must point to a local PostgreSQL role allowed to create throwaway databases.
../.venv/bin/pytest -q
```

## Recovery and limitations

Rollback code to the preceding known-good commit if needed; keep the additive schema and cloud drafts so recovery
copies are not destroyed. Do not drop audit rows or reverse approved/published content to roll back a UI change.
Review queued/cancelled requests explicitly before retrying them.

Local editor drafts remain device-specific; only creation bookmarks sync between devices. Browser storage denial
is shown honestly. A power loss before the browser commits a keystroke or before cloud sync completes cannot be
promised recoverable. An ambiguous Telegram timeout may already have delivered the message; retries can produce
a duplicate. An external model request cannot be recalled once submitted, and cancellation does not refund tokens.

## Facebook Stories and long videos (migration 16)

Migration `20261102000016_facebook_stories_long_videos.sql` lets a post be a `story` and lets the Facebook Page's
posting schedule hold Stories and long videos. Apply it with **GitHub → Actions → First-time setup (keys only)**.
Until then, Facebook schedules still save; asking for Stories or long videos shows a message to run the update.

- **Stories:** each Story reuses one of the week's Reels and goes up 3 hours after it. It takes no posting slot,
  has no caption, and is never blocked as a repeat of its Reel (its fingerprint is marked as a Story; two identical
  Stories are still stopped).
- **Long videos:** the YouTube title and description (with its disclaimer) go to the Page as a video, uploaded in
  pieces. They take a posting slot after the Reels and text posts, so add a posting day or time if the week is full.
- Nothing changes until the owner sets **Stories per week** and **Long videos per week** for the Facebook Page in
  Settings → Posting schedule. Ads are not part of the studio.

## Improvement phases 1-5 (migrations 17-20)

Merge the PRs in order (Phase 1, 2, 3, 4, 5), then run **GitHub → Actions → First-time setup (keys only)** once; it
applies every missing migration in order. Each phase works before its migration lands: the new job types, tables and
functions are only used once they exist, and the dashboard says "needs the latest database update" instead of failing.

- **17** `remake_shorts`: new Shorts for a package from its own checked facts; hand-posted texts marked published.
- **18** `preview_scene`: render one scene on its own; the Freesound key can be saved from Setup.
- **19** Performance: `post_metrics`, `account_metrics`, `provider_usage.project_id`, `studio_performance()`,
  `studio_package_costs()`. Collected once a day by maintenance, read-only.
- **20** `affiliate_offers`: owner-entered, https only, disclosure first, long-video descriptions only.

Storage: stock clips are trimmed to 20 s and compressed (a few MB); clips, previews and final renders of decided
projects are cleaned up after 7 days, but a clip stays while any post of its project still has to go out.

## Quality pack (migration 21)

An outside review of an older copy (26 Oct) listed 12 points; each was checked against the current code. Already
done: missing Shorts (PR #31), animations and scene preview (Phases 1-2), SEO and learning from results (Phases 3-4).
The rest is fixed here:

1. **Final video named by its content.** The final file's name includes a fingerprint of the recipe and its media,
   so a reused workspace never posts a video made before an edit.
2. **Facebook's explicit yes.** A Reel counts as posted only when Facebook answers `success: true`; a text post only
   with a post id. Anything else is "please check" (needs review), never "posted".
3. **Facebook errors say what to do.** Meta's error codes are read: an expired login (190, 102, …) or a missing
   permission (10, 200-299) marks the connection for reconnecting; a rate limit (4, 17, 32, 613) is retried later.
4. **Facebook connection.** The Worker asks Facebook which permissions were really granted, refuses a login that
   can't post on the Page, keeps the already-connected Page on reconnect, and with several Pages lets the owner choose
   (the list travels encrypted and expires in 15 minutes; nothing is saved before the choice).
5. **Approval of the current version.** The publisher needs the post's approval and the package's approval for the
   script version that is current now.
6. **Approving with problems needs a reason** (`approve_project`, migration 21): with unsupported or contradicted
   facts, or parts needing attention, the owner writes why (at least 10 characters). The reason is kept with the
   approval and in the audit log (`approved_with_problems`). Review shows "Passed checks / Needs corrections" and
   "Approved by you / Waiting for your approval" as separate answers, and the dialog lists what's included and missing.
7. **Clock changes.** A posting time the clocks skip moves later by the jump (02:30 → 03:30); a time that happens
   twice uses the first. The owner gets a note (Telegram routine alert, `schedule_note`).
8. **Capacity.** Estimates use the configured length (11 min) or the measured length of recent final renders, the
   measured render speed, animated scenes and a retry allowance; `plan_batch` returns these assumptions.
9. **Browser tests on GitHub.** The Tests workflow runs every browser suite (`browser` job), including the new
   `e2e/quality.mjs`; engine, Worker and dashboard tests cover each fix above.
10. **Photos.** The best-matching result is chosen (words in its description, then size), not the first; when no photo
    is found, the reason is saved on the scene and shown in Review.
11. **Facebook schedules.** Reels and text posts can have their own days and times (`reel_days/reel_times`,
    `text_days/text_times`, migration 21); without them they use the Page's, exactly as before. The schedule card
    shows the next 7 days: asked for, really scheduled, and why any gap is there.
12. **Settings → Accounts** shows, from a daily engine check (`account_capabilities` setting): login saved, needed
    permissions granted, posting automatic / drafts / not possible, last post that worked, last problem, next step.
13. **Drafts.** Each draft says "Saved to your account" or "Saved on this device" (syncing / sync unavailable); cloud
    drafts and job history are read page by page instead of a fixed 200 rows. Signing out or switching account
    clears cached data (tested).

Rollout: everything except points 6 and 11 works before migration 21. Before it, the old approval function is used
(no reason asked by the database; the dashboard still asks), and separate Facebook times show a message to run the
update. Apply it with **GitHub → Actions → First-time setup (keys only)**.

## Script reliability (migration 22)

Why packages never reached Ready for review, and the fix: see `docs/SCRIPT_RELIABILITY.md`. In short:
- facts keep their passage, source and date, and are saved with each script version;
- the checker sees the full evidence;
- repair is targeted and bounded, with a final check of the saved version;
- Shorts are repaired one by one;
- results are blockers, warnings, missing parts or notes.

Migration 22 allows the claim status `general` (a general principle), the script origin `repair`, and the owner job
`repair_package` (Review → Recheck and repair). Before it is applied, new scripts store principles as opinions with a
note, and the repair button says to run the update. Apply it with **GitHub → Actions → First-time setup (keys only)**.
