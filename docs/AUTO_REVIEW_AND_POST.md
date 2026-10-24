# Auto Review & Post (v2.4, fix and retry in v2.5)

One switch decides who approves publishing. **Default: OFF.**

| | OFF (manual, default) | ON (automatic) |
|---|---|---|
| Who approves | You, in Review (unchanged) | The automatic review, for packages that pass everything; you for the rest |
| What posts | Only what you approve | Auto-approved packages, at their normal scheduled times |
| Telegram | "Your week is ready", posted / problem alerts (unchanged) | Plus "✅ Auto-approved: …" or "👀 Needs your review: …" with the reasons |

## Where to switch it

* **Dashboard:** Settings → Automation (and each package page in Content, and Create before **Create package**). The status *Auto Review & Post: ON/OFF* is always shown in
  the menu. Turning ON asks for confirmation; turning OFF is immediate.
* **Telegram:** `/autopost` (status), `/autopost on confirm`, `/autopost off`. `/status` shows the mode too. Only the
  linked owner chat is obeyed.

Both call the same database function `set_auto_review_post`, so a change on one side shows on the other within
about 10 seconds (the dashboard re-reads the mode every 10 seconds and when you return to the tab). The mode is a
database setting, so it survives restarts. The browser can't write that setting directly; only the function can,
and it accepts only the owner, the Worker (service role) or the engine.

## What "passes every check" means

A package (a long video and its Shorts) is auto-approved only if **all** of these are true:

1. Every part passed the existing quality gates (status *Ready to review*, not *Needs a look*).
2. No open quality issues.
3. Every claim is supported by a source (and there is at least one).
4. Time-sensitive facts stay fresh for at least 48 hours.
5. There are posts waiting to be scheduled.
6. Every post goes to an enabled, configured account, and each scheduled post matches its variant's account.
7. Every post is ready (none needs attention).
8. No banned or generic phrases in the post text.
9. Money channel: the disclaimer is in every long-video description.
10. Every stock photo has a licence record.
11. An independent AI review (the critic role) says it is publishable, with **≥ 85% confidence**, **no policy flags**
    (misleading claims, medical/financial advice, harassment, hate, adult, dangerous acts, copyright, impersonation)
    and **no accuracy or quality issues**.

If any check fails, or anything errors, the package stays *waiting for approval* and you get a Telegram message with
the reasons. The mode is re-read immediately before approving (inside a database transaction that locks the
package), so switching OFF mid-run stops it, and a package you approved or rejected meanwhile is left alone.

## Fix and retry (v2.5)

When a check fails, the studio repairs only that part and runs **every** check again, up to `max_attempts` times
(Settings → Automation, 0–5, default 3; setting `auto_review_fix`):

| Failed check | Fix |
|---|---|
| Banned phrases in post text | Simple swaps, then a model rewrite of that post only (done at once) |
| Money disclaimer missing | The channel disclaimer is added to the description (done at once) |
| Posts not ready although the video is | Posts marked ready again (done at once) |
| Quality gates, open issues, unsupported claims, AI reviewer unsure or reporting issues | `regenerate_script` job with the reviewer's notes as instructions, then re-render |
| Stock photo without a licence | `rerender_preview` job |
| Facts expiring within 48 hours | `recheck_project` job |
| Wrong or disabled account, nothing to post, any policy flag | **Never retried**: sent to you |

Each attempt is an `auto_reviews` row with verdict `fixing`, the attempt number and what was changed, an audit entry
(`auto_review_fixing`) and a Telegram message "🔧 Fixing: …". Queued fixes run in the same queue run (up to 4 rounds),
then the package is reviewed again automatically. When it passes, a post whose time slot passed while it waited moves
to the account's next free slot instead of going out at once. If it still fails after the last attempt it waits for
you ("Still failing after N automatic fix attempts"). The mode is re-read before every fix and before approving.

## Publishing safety (unchanged)

Auto-approval writes the same approval records as your manual approval (marked `source = auto_review`) and sets the
same statuses, so the existing publish runner treats it exactly like your approval: only approved posts with an
approval record, matching account, fresh facts, licensed media, one publication per post (no duplicates), and posts
only to the accounts configured for the studio. Posted/blocked/failed messages reach Telegram as before.

## Switching OFF

Every package from then on waits for you. Auto-approved posts that haven't started publishing go back to *waiting for
approval* (shown as "N post(s) back in Review"); posts already published are not touched.

## Audit trail

* `audit_logs`: `auto_review_post_on` / `auto_review_post_off` (actor `owner` or `telegram`), and
  `auto_review_approved` / `auto_review_needs_review` / `auto_review_error` per package.
* `auto_reviews`: one row per package and script version with every check, the reasons, the AI reviewer and its
  confidence, and how many posts were scheduled. Shown in Settings → Automation → *Recent automatic reviews*.
* `approvals.source`: `owner` or `auto_review`.

## Reference

| Item | Value |
|---|---|
| Migration | `20261024000007_auto_review_post.sql` |
| Setting | `auto_review_post` (missing = OFF) |
| Function | `set_auto_review_post(p_on boolean, p_actor text)` |
| Worker | `POST /api/autopost {on, confirm}` (owner only; ON needs `confirm: true`), Telegram `/autopost` |
| Engine | `studio/review/auto.py`; runs after each production batch, after owner jobs, and as the `auto_review` job when switched ON |
