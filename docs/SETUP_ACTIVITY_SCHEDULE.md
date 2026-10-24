# Setup page, Activity page, posting schedule, Clear and the Simple menu (v2.5)

## Setup page (now Settings → Getting started, `/settings/setup`; `/setup` redirects)

One page for every connection, in order, each with a live check:

| Step | Done when | Values you can paste here |
|---|---|---|
| 1. The basics | Database reachable, encryption key works, GitHub token can start the engine, dashboard address set | none (they must stay in GitHub) |
| 2. Telegram | Bot token set and your chat linked | `TELEGRAM_BOT_TOKEN` (the webhook secret is made for you) |
| 3. AI keys | At least one provider passed the last key check | added on the AI APIs page |
| 4–7. YouTube, Facebook, TikTok, X | Every account of that platform is connected | `GOOGLE_CLIENT_ID/SECRET`, `FACEBOOK_APP_ID/SECRET`, `TIKTOK_CLIENT_KEY/SECRET`, `X_CLIENT_ID/SECRET` |
| 8. Research keys (optional) | A YouTube Data API key is set | `YOUTUBE_API_KEY`, `PEXELS_API_KEY`, `PIXABAY_API_KEY`, `FRED_API_KEY`, `SEC_USER_AGENT` |
| 9. Posting schedule | You pressed "The schedule looks right" | |
| 10. First video | Any video exists | |

**How values are stored.** The browser sends the value once to the Worker (owner session required). The Worker
checks its format, encrypts it with AES-256-GCM using `TOKEN_ENCRYPTION_KEY` (the same format as social logins) and
stores it in `app_secrets`, a table no browser role can read or write. Only a hint (`••••` + last 4) is stored in the
clear; the audit log records the name and hint, never the value. Only the 15 names above are accepted.

**How they are used.** The Worker overlays saved values on its settings for every request (cached for 60 seconds,
cleared on save). The engine loads them into its environment when it connects (`studio/secrets.py`). A saved value
wins over the GitHub secret of the same name; GitHub secrets keep working when nothing is saved. Removing a saved
value falls back to GitHub.

**Live tests on Save & test.** Telegram `getMe`; Google token endpoint (a wrong pair returns `invalid_client`, a right
pair `invalid_grant`); Facebook and TikTok app-credential tokens; YouTube, Pexels, Pixabay and FRED API calls. X can
only reject a wrong pair; a right one is confirmed when you press Connect. Saving the bot token also creates the
webhook secret and points the bot at the Worker. Telegram webhooks are accepted with either the Setup-page secret or
the GitHub one, so a later *Deploy Worker* can't break the bot.

**Must stay in GitHub:** `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `SUPABASE_ANON_KEY`, `SUPABASE_DB_URL`,
`TOKEN_ENCRYPTION_KEY`, `CLOUDFLARE_API_TOKEN`, `CLOUDFLARE_ACCOUNT_ID`, `WORKER_GITHUB_TOKEN`, and the `DASHBOARD_URL`
variable. The engine records which of the movable names exist as GitHub secrets (true/false only) each time it runs
in GitHub Actions, so Setup can say *Also in GitHub: safe to remove there*.

## Activity page (`/activity`)

* **Running now:** queued and running jobs, with the step the engine reports (`generation_jobs.progress`,
  e.g. `{"label": "Step 3 of 5: removing duplicates", "step": 3, "total": 5}`). Weekly research and production runs
  are recorded as jobs too (`weekly_research`, `weekly_production`), so they show while they run.
* **Today so far:** ideas found, videos made, approvals, posts, problems.
* **How the studio works:** Ideas → Research → Write → Check → Review → Post, with how many items are at each step.
* **Timeline:** finished and failed jobs, every notification (posted, auto-approved, fixing, needs you, blocked…)
  and owner setting changes, newest first, filterable. Every problem has a button to the fix.
* The menu shows the same "Working: …" or "Studio idle" line on every page.

## Posting schedule (Settings → Posting schedule)

Per account: posting days, up to 4 times a day, posts per week per type (YouTube long videos and Shorts have their
own days and times; Facebook Reels and text posts share slots), and Posting/Paused. The preview shows the week; the
warnings cover targets that don't fit the chosen slots, posts less than an hour apart, and YouTube's daily upload
limit. Saving calls `set_posting_schedule` (owner only, validated, audited); ticking *move* re-times waiting posts
into the new slots in order. *Reset to default* uses `config/accounts.yaml` (stored by each config sync in the
`posting_schedule_defaults` setting). Config syncs never overwrite the dashboard schedule.

## Clear buttons

Clearing a history list stores a "cleared at" time in the `ui_cleared` setting and hides older items from that list;
nothing the studio needs is deleted, and **Undo** restores the previous time. Real actions are: *Clear new ideas*
(moves New ideas to Archived; Undo moves exactly those back), *Cancel this post* (Calendar; Undo restores its status)
and *Discard package* (Review; rejects and cancels its posts). *Reset usage stats* on AI APIs changes only what the
page counts; daily key limits still count every call. Published posts and the audit log can't be cleared.

## Menu, tour and plain labels

v2.6 replaced the Simple/Advanced menu with five fixed pages (Home, Create, Content, Calendar, Activity) for everyone;
the old `ui_mode` setting is no longer read. A 5-card tour runs the first time (`tour_done`); Help replays it.
Technical panel names are plain ("What the AI did", "Jobs in progress", "Who's working", "Ready to run"), with a "?"
explanation. Quick actions moved out of Mission Control onto the Activity page.

## Reference

| Item | Value |
|---|---|
| Migration | `20261025000008_setup_schedule_activity.sql` |
| New table | `app_secrets` (no client access) |
| New columns | `generation_jobs.progress`, `auto_reviews.attempt`, `auto_reviews.fix` (unique now per project, script version and attempt; verdict `fixing`) |
| New functions | `set_posting_schedule(account, schedule, move)`, `schedule_slots(...)` (internal) |
| Settings keys | `ui_mode`, `ui_cleared`, `tour_done`, `setup_progress`, `auto_review_fix`, `posting_schedule_defaults`, `engine_env_presence` |
| Worker endpoints (owner only) | `POST /api/setup/status`, `/api/setup/save`, `/api/setup/test`, `/api/setup/remove` |
