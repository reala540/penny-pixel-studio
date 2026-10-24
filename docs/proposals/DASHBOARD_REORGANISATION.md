# Penny & Pixel Studio: dashboard reorganisation proposal (revision 2)

Status: **proposal only.** No code has been changed, pushed or deployed. Implementation starts only when you ask.

This revision applies your decisions and conditions, and replaces earlier assumptions with checks made against
the live database and the code (section C).

| Your condition | Where it's handled |
|---|---|
| B1 is required: "Create package" makes exactly the selected idea; weekly batch stays separate | Part B (backend), A.3.2 step 4 |
| Defer B3: no "Post now" that publishes everything due | D.1 (deferred); no Post now button anywhere in Part A |
| Telegram optional for creating content | A.3.1 (readiness), A.3.6 (Getting started) |
| Always show whether approval is manual or Auto Review & Post | A.2 (menu), A.3.2 step 4, A.3.3 approval card |
| Show only real progress and supported retries | C.3, A.3.2 step 5 |
| Verify the AI failure before proposing a fix | C.1 (diagnosis: configuration and provider availability, no code fix required) |
| Verify which features need backend work | C.2 (every data claim checked) |
| Keep old links, OAuth returns, features, safeguards | A.1 redirects, A.4 mapping, A.7 safeguards |
| Both channels for research and ideas only | A.3.2 step 1 |
| Run now has one home: Activity → Quick actions, visible | A.3.5; Settings → Automation links there |

---

# Part A — Interface changes (front end only)

Everything in Part A uses data and actions that exist today, **except** where it says *needs B1*.

## A.1 Sitemap

```
Primary
├── Home                 /
├── Create               /create            steps: channel · idea · research · package · progress · review · schedule
├── Content              /content           tabs: Needs you · In progress · Approved & scheduled · Published · Not used · All
│   ├── Ideas            /content/ideas     generated ideas + weekly research ideas in one list
│   └── Project page     /content/:id       tabs: Video · Script · Sources & checks · Thumbnails · Shorts · Posts · History
├── Calendar             /calendar          (?post=:id opens a post)
└── Activity             /activity          Now · Quick actions · Today · Timeline · Problems · Technical details ▸

Secondary: Settings /settings/<section> · Help /help · Sign out
Public (unchanged): /privacy · /terms · /demo
```

**Old addresses keep working (redirects, query strings and anchors kept):**

| Old | New | Why it matters |
|---|---|---|
| `/review/:id` | `/content/:id` | Every Telegram "Open dashboard" link for a package |
| `/review` | `/content?tab=needs-you` | "Your week is ready" Telegram link |
| `/calendar`, `/calendar?post=` | unchanged | Telegram `/week` link |
| `/settings?connected=…` / `?connect_error=…` | `/settings/accounts?connected=…` (the toast still shows) | **OAuth return** from YouTube, Facebook, TikTok, X (the Worker redirects to `/settings?…`) |
| `/settings#accounts`, `#automation`, `#posting-schedule`, `#telegram`, … | matching `/settings/<section>` | Links from Activity fix buttons and docs |
| `/setup`, `/setup#telegram` | `/settings/setup` (+ anchor) | Fix buttons |
| `/api` | `/settings/ai` | Fix buttons |
| `/week` | `/` | |
| `/library` | `/content?tab=all` | |
| `/ideas` | `/content/ideas` | |
| `/research` | `/content/ideas?source=research` | |
| `/mission`, legacy `/` Mission Control | `/activity` | |
| `/help`, `/privacy`, `/terms`, `/demo` | unchanged | |

The Worker's OAuth callback keeps redirecting to `/settings?connected=…`; the dashboard's redirect handles it, so
no Worker change is needed.

## A.2 Navigation

**Desktop:** fixed left menu with Home · Create · Content (count of items needing you) · Calendar · Activity (● when
something runs or a problem is open). Below them, two status lines that never move:

* `◌ Working: <current step>` or `Studio idle` → Activity
* **`Approval: You approve` / `Approval: Auto Review & Post`** → Settings → Automation (this is the persistent
  manual-or-automatic indicator)

Then Settings · Help · Sign out · theme. It scrolls with the **More ↓** arrow on short screens (as today).
**Breadcrumbs** on deeper pages: `Content › Needs you › Spotting Fraud: 5 Red Flags`.

**Phone:** a fixed bottom bar with the same 5 items; the top bar has the working indicator and **More** (Settings,
Help, Approval mode, Theme, Sign out). The Simple/Advanced menu is retired; advanced controls sit in "More options"
and "Technical details" sections on their own pages.

## A.3 Pages

### A.3.1 Home (`/`): permanent landing page

```
┌────────────────────────────────────────────────────────────────────────────┐
│ Home                                                 [ + Create content ]  │
│ Approval: You approve each package            (or: Auto Review & Post ON)  │
├────────────────────────────────────────────────────────────────────────────┤
│ NEEDS YOU  (problems → ready for review → quick jobs → setup)               │
│ ✕ Writing stopped for "Budget jump": no AI service could summarise the     │
│   research                                          [ Check AI services ]  │
│ ▶ "Spotting Fraud" is ready for review              [ Review ]             │
│ ✋ Quick job: post "AI pricing" on TikTok yourself   [ Download ] [ Done ]  │
├──────────────────────────────────┬─────────────────────────────────────────┤
│ BEING MADE NOW                   │ NEXT POSTS                              │
│ "Budget jump" · Rendering        │ Mon 18:00 YouTube AI "AI pricing"       │
│   previews (2 of 4 done)         │ Tue 12:30 Facebook   Reel               │
│ [ See Activity ]                 │ [ Open calendar ]                       │
├──────────────────────────────────┴─────────────────────────────────────────┤
│ THIS WEEK  ‹ prev | This week | next ›   29 planned · 6 published · …      │
│ (rundown grid as today)                                                    │
├────────────────────────────────────────────────────────────────────────────┤
│ Studio health ▸   ·   Notifications: Telegram not linked (recommended) ▸   │
│                                                        [ Pause publishing ]│
└────────────────────────────────────────────────────────────────────────────┘
```

* **One primary action: Create content.** It's disabled with a reason only when the studio **can't create**:
  * the core GitHub settings fail (database or Worker unreachable), or
  * the last key check found **no working AI service**.

  The reason line links to the fix.
* **Telegram is never required.** If it isn't linked, a dismissible "Recommended: get alerts on your phone" line
  links to Settings → Notifications.
* **Social accounts aren't required to create.** Home shows "Ready to create ✓ · Ready to publish: 2 of 5 accounts
  connected", and Needs you lists unconnected accounts that have posts waiting.
* **Needs you** draws on existing data:
  * failed or blocked jobs and posts;
  * packages ready for review or needing a look;
  * open quick jobs (manual tasks) with Download / Open / Done;
  * "Configuration required" (no working AI service);
  * accounts needing reconnection.
* **Phone:** one column in the same order; the rundown becomes a day list.
* **Empty:** "Nothing needs you right now." plus the next post, or "Nothing planned yet. **Create content** to fill
  your week."
* **Loading:** skeletons per card. **Error:** "Couldn't load *Next posts*. **Try again**" in that card only.

### A.3.2 Create (`/create`): the guided flow

A progress bar shows `1 Channel · 2 Idea · 3 Research · 4 Package · 5 Progress · 6 Review · 7 Schedule`. Back is
always allowed; choices are kept on this device until finished.

**Step 1 · Channel.** Pixel (AI) or Penny (Money). A separate, clearly labelled link: **"Find ideas or research for
both channels"**, which opens step 2 in *ideas-only* mode (Generate ideas and Research only; no package button).
Creating a package always needs one channel.

**Step 2 · Choose or generate an idea.** One list of the channel's ideas:

| Kind | Where it comes from |
|---|---|
| **Idea Generator** ideas | `generated_ideas`, with score, confidence and evidence |
| **Weekly research** ideas | `content_ideas`, with score breakdown and sources |

Each card has a kind label and its existing actions:
* Idea Generator: Use this idea · Save · Not for me · Refine · Archive / Restore · Why this score.
* Weekly research: Use this idea · Shortlist · Save for later · Drop.

Other ways to get an idea:
* **Generate new ideas** queues the existing `generate_ideas` job (with the channel override the job already
  supports).
* **Write my own idea** is the existing objective box, with Council depth under **More options**.

**Step 3 · Check the research.** The idea's real, dated sources:
* Idea Generator: `trend_signals` and evidence.
* Weekly research: `source_ids` → `research_sources`.

Also shown: the idea's care notes. Actions: **Looks good, continue** · **Research it deeper** (the existing
`run_research` with this idea as the brief, this channel and the council depth) · **Choose another idea**.

**Step 4 · Create the package** (*needs B1*).
```
"Spotting fraud: 5 red flags" · Penny
Makes: a long video, its Shorts, thumbnails and a post for each enabled account.
Approval: You approve it in Content before anything is posted.
   (or) Auto Review & Post is ON: if every check passes it's approved automatically and posts
        at its scheduled times; otherwise it waits for you.            [Change in Settings]
                                                            [ Create package ]
```
* No time estimates and no promised Short or post counts. The real counts appear once the package exists.
* **Make this week's videos** (the batch) is not on this screen. It lives in Activity → Quick actions and is
  labelled as a batch: "Makes every shortlisted idea for the week, up to your free capacity."

**Step 5 · Progress: only what the engine reports.** For the project, the step list comes from its stage jobs
(C.3):

```
✓ Script written and facts checked          (stage: script)
✓ Shorts, titles and post texts             (stage: package)
◌ Rendering previews · 2 of 4 done          (stage: render_preview, one per video/Short)
○ Thumbnails                                (stage: thumbnails)
○ Final checks → Ready for review / Needs a look
Current step (when the job reports one): "Making money video 1 of 1"
```
* Each line shows its real status: waiting, running, done, or **didn't work** with the stored error in plain
  words. There's no percentage bar and no time estimate.
* **Retry buttons appear only where a matching retry exists** (C.3). With B1, every stage gets **Try again from this
  step** (it resumes; finished stages aren't redone). Without B1, script, package and stages that never started have
  no complete retry, and the screen says so instead of offering a button.
* "You can leave this page." The link to Activity is always there. Telegram is mentioned only if it's linked.

**Step 6 · Review** opens the project page (A.3.3) with the approval card.
**Step 7 · Schedule** opens the project's Posts tab: each post's planned slot, the existing change-time action
(Calendar rules, including the 30-minute clash check), then **Approve package**. With Auto Review & Post ON, the page
shows the automatic decision instead.

* **Phone:** one step per screen with a sticky Continue button.
* **Empty (step 2):** "No ideas for Penny yet. **Generate new ideas** or **write your own**."
* **Errors:** the job error in plain words. "Configuration required" links to Settings → AI services. If the Worker
  is missing, buttons can't start jobs: "The studio can't start work: the Worker isn't connected. **Fix in Getting
  started**." (Verified: owner jobs are only started by the Worker; the queue workflow has no schedule of its own.)

### A.3.3 Content and the project page

**Content tabs** (existing statuses):
* **Needs you:** ready for review + needs a look, with **Approve all that passed every check**.
* **In progress:** writing / checking / rendering.
* **Approved & scheduled.**
* **Published:** with the existing "Posted on" links.
* **Not used:** rejected / failed / archived, with *Clear drafts* (Undo).
* **All:** today's Library table with search and the channel, format and status filters.

**Ideas** (`/content/ideas`): both idea tables in one list, with a Source filter (Idea Generator · Weekly research ·
Both).
* Today's status tabs, search, sort, generation history (Clear, Undo), *Clear new ideas* (Undo), research week
  grouping, *Clear old research* (Undo).
* "Used" means *Sent to Studio* today; with B1 it links to the project that was made.

**Project page** (`/content/:id`):
```
Content › Needs you › Spotting Fraud: 5 Red Flags              ● Penny · Video · Ready for review
[ Video ] [ Script ] [ Sources & checks ] [ Thumbnails ] [ Shorts ] [ Posts ] [ History ]
                                                   ┌ APPROVAL ─────────────────────────┐
  (tab content)                                    │ You approve this package          │
                                                   │   (or: Auto Review & Post ON:     │
                                                   │    last automatic review + reasons)│
                                                   │ ✓ Passed every check / ⚠ 2 to look at│
                                                   │ [ Approve package ]   ← primary    │
                                                   │ [ Rewrite with a note ]           │
                                                   │ [ Discard package ]               │
                                                   └───────────────────────────────────┘
```

| Tab | Contents (all existing) |
|---|---|
| Video | Preview player, quality box, freshness date |
| Script | Scene editor, **Save and re-render** (new version), Undo changes, version label |
| Sources & checks | Claims with sources and status, quality gates, automatic review result and fix attempts |
| Thumbnails | Options, phone preview, **Choose**, words + **Make new thumbnails** |
| Shorts | Previews and titles |
| Posts | Per account: edit text with limit, planned time, **Skip this post**, change time (Calendar rules) |
| History | Built from rows that carry this project's id (see C.2): jobs, automatic reviews, approvals, posts and published links. Notifications appear only when their link names the project |

* Decided packages are shown read-only.
* **Phone:** the approval card becomes a sticky bottom bar.
* **Expired preview:** "This preview was cleaned up to save space. **Re-render preview**" (existing).

### A.3.4 Calendar

Unchanged in function:
* week picker and account filter;
* drag to another day with the clash rule, plus an exact time change;
* **Re-check the facts**;
* **Try again** for failed posts and "check on the platform" posts, with the existing warning;
* **Cancel this post** (Undo) and Open the post;
* "Open the package" → project page.

Plain statuses (A.6). **Phone:** a day list, with the post panel as a bottom sheet. **No "Post now"** (deferred, D.1).

### A.3.5 Activity

```
Activity                                                       [ Clear history ] (Undo)
NOW            running and queued jobs with their reported step ("starts within 15 minutes" when queued)
QUICK ACTIONS  (always visible: the single home of "Run now")
               [ Research this week ]  [ Make this week's videos (batch) ]  [ Publish approved & due posts ]
               each explains itself, e.g. "Publishes every approved post whose time has come."
TODAY          ideas found · videos made · approved · posted · problems; How the studio works (6 steps)
TIMELINE       filters; every problem has a fix button
PROBLEMS (n)   the same items filtered, oldest unresolved first
▸ Technical details   AI calls (filters, Pause feed, Refresh) · Who's working · Model council · Jobs
                      (Cancel queued, Clear finished) · Ready to run
```
"Publish approved & due posts" keeps its wording and only publishes posts that are approved and due, as today.

### A.3.6 Settings

| Section | Contents |
|---|---|
| **Getting started** | Today's Setup checklist, split into **Needed to create** (basics, AI services) · **Needed to publish** (each platform) · **Recommended** (Telegram notifications, research keys, posting schedule review). The progress bar counts only "Needed" items |
| **Accounts** | Connect / Reconnect, status, last error; OAuth return toasts |
| **Posting schedule** | Unchanged editor |
| **Automation** | Pause/Resume publishing; Auto Review & Post switch (confirmation); fix attempts; automatic review log; idea batch schedule; recent idea runs; **"Run something now → Activity › Quick actions"** link (no buttons duplicated here) |
| **Ideas & research** | Idea Generator configuration |
| **AI services & keys** | Today's AI API Manager plus the AI writers on/off table, including **Models and the jobs they do** (where C.1's configuration fix happens) |
| **Channel voices** · **Notifications (Telegram, optional)** · **Budget** · **Appearance & region** | As today |

### A.3.7 Help

Today's content, updated to the new names, plus a contextual **?** on each page header.

## A.4 Feature-to-page mapping (every current feature)

| # | Feature today | Now | Proposed |
|---|---|---|---|
| 1 | Sign in / sign up, owner claim, "already has an owner", "Almost there" | AuthGate | Unchanged |
| 2 | Skip link, paused banner, toasts with Undo | Layout | Unchanged |
| 3 | Working / idle indicator | Menu | Menu status line; phone top bar |
| 4 | Auto Review & Post badge | Menu | Menu "Approval:" line; phone More |
| 5 | Theme | Menu, Settings | Menu; Settings → Appearance |
| 6 | Simple / Advanced menu | Menu, Settings | Retired → "More options" / "Technical details" sections |
| 7 | Tour, Replay | Layout, Help | Kept, rewritten for the new menu |
| 8 | Rundown grid, week picker, summary | This Week | Home → This week |
| 9 | Pause / Resume publishing | This Week | Home + Settings → Automation |
| 10 | Waiting for you | This Week | Home → Needs you |
| 11 | Quick jobs: Download / Open / Done | This Week | Home → Needs you |
| 12 | Studio health (writers, X spend, problems, Clear) | This Week | Home → Studio health |
| 13 | Objective, channel, council depth, outcome, Launch, Clear objective, idea prefill | Mission Control | Create steps 1–4 (Write my own; More options). "Outcome: research" → step 3 Research it deeper; "Research + package" → step 4 (B1) |
| 14 | Idea Generator panel (Generate, Regenerate, Clear batch, config alert, run notes) | Mission Control | Create step 2 + Content → Ideas |
| 15 | Status header, clock, counts, Pause feed, Refresh | Mission Control | Activity → Technical details → AI calls |
| 16 | Model council | Mission Control | Activity → Technical details |
| 17 | Who's working | Mission Control | Activity → Technical details |
| 18 | What the AI did + filters | Mission Control | Activity → Technical details → AI calls |
| 19 | Jobs: Cancel queued, Clear finished | Mission Control | Activity → Technical details → Jobs |
| 20 | Quick actions: research / build packages / publish due | Mission Control | **Activity → Quick actions (visible)** |
| 21 | Ready to run | Mission Control | Activity → Technical details; blockers on Home |
| 22 | /demo | Mission Control | Kept (sample data on Activity + Create) |
| 23 | Running now, Today, How it works, Timeline, filters, fix buttons, Clear history | Activity | Activity |
| 24 | Review list, Approve all that passed | Review | Content → Needs you |
| 25–31 | Preview, quality box, script editor, facts, thumbnails, posts editor, Shorts, Approve / Rewrite / Discard | Review detail | Project page tabs + approval card |
| 32 | Auto Review switch on Review | Review | Approval card shows the mode and links to the switch in Settings → Automation |
| 33 | Library table, filters, Posted-on links, Clear filters, Clear drafts | Library | Content → All / Published / Not used |
| 34 | Idea Library tabs, search, sort, Generate, Clear new, Clear filters, history | Ideas | Content → Ideas |
| 35 | Idea card actions | Ideas | Content → Ideas + Create step 2 |
| 36 | Research ideas by week, score breakdown, sources, Shortlist / Save / Drop, channel filter, Clear old research | Research | Content → Ideas (Source: Weekly research) + Create steps 2–3 |
| 37 | Calendar | Calendar | Calendar |
| 38 | Setup checklist, secret fields, Copy, "safe to remove" | Setup | Settings → Getting started (regrouped) |
| 39 | Accounts Connect / Reconnect, OAuth toasts | Settings | Settings → Accounts |
| 40 | Posting schedule editor | Settings | Settings → Posting schedule |
| 41 | Auto Review switch, fix attempts, review log, idea schedule, idea runs | Settings | Settings → Automation |
| 42 | Run now (research / produce / publish) | Settings | **Activity → Quick actions** (Settings links there) |
| 43 | Idea generation config | Settings | Settings → Ideas & research |
| 44 | AI writers table | Settings | Settings → AI services & keys |
| 45 | AI API Manager | AI APIs | Settings → AI services & keys |
| 46–48 | Channel voices · X budget · Timezone | Settings | Same names in Settings |
| 49 | Telegram link code | Settings, Setup | Settings → Notifications (optional) |
| 50 | Help, FAQ, Replay tour | Help | Help + contextual ? |
| 51 | Privacy, Terms | Public | Unchanged |
| 52 | "?" term explanations | Mission Control | Wherever the term appears |

Telegram bot commands, the Worker API, the engine and all workflows are untouched by Part A.

## A.5 States and confirmations

**States (same pattern everywhere):**

| State | Pattern |
|---|---|
| Loading | Skeletons at the final size; busy buttons say "Saving…", "Queueing…" |
| Empty | One sentence plus the one next action |
| Error in an area | Inline: plain reason + **Try again** + fix link (existing `fixFor` rules) |
| Failed save | Input kept: "Couldn't save: {reason}. Nothing was changed." |
| Can't create | Create disabled with the reason (no working AI service, or Worker/database unreachable) |
| Paused | Banner on every page; creating still works and says nothing will post while paused |

**Confirmations (wording):**

| Action | Title | Body | Button |
|---|---|---|---|
| Approve package | Approve this package? | The video, its Shorts and {n} posts go out at their scheduled times. You can still cancel single posts in Calendar. | Approve package |
| Approve all | Approve {n} packages? | Only packages that passed every check are approved. The rest stay for you. | Approve {n} |
| Discard package | Discard this package? | The video, its Shorts and all their posts are rejected and their slots freed. It stays in Content → Not used. | Discard package |
| Cancel a post | Cancel this post? | It won't go out and its slot is freed. Nothing else changes. You can undo this for a few seconds. | Cancel this post |
| Skip a post | Skip this post? | This account won't get this post; the rest of the package is unchanged. | Skip post |
| Create package (B1) | — (no confirmation: nothing is posted by creating; the approval line on the screen explains what happens next) | | |
| Make this week's videos | Make this week's videos? | Makes every shortlisted idea for the week, up to your free capacity. Each package waits for approval (or Auto Review & Post). | Start batch |
| Publish approved & due | Publish approved posts that are due? | Only posts that are approved and whose time has come are published, with every usual check. | Publish due posts |
| Pause / Resume | (existing wording) | | |
| Auto Review & Post ON | (existing wording) | | Turn on |
| Remove API key / Setup value | (existing wording) | | Remove |
| Clear lists / Clear new ideas | (existing wording, Undo) | | Clear |
| Move waiting posts | Move {n} waiting posts? | They move to the new days and times in order; published or publishing posts stay put. | Save and move |

## A.6 One status vocabulary

| Stored | Shown |
|---|---|
| scripting / verifying / rendering | Writing · Checking facts · Making the video |
| ready_for_review / needs_attention | Ready for review · Needs a look |
| approved / scheduled / publishing / published | Approved · Scheduled · Posting now · Published |
| pending_approval (post) | Waiting for approval |
| needs_manual / needs_review (post) | Post it yourself · Check on the platform |
| blocked | On hold: facts need a re-check |
| failed | Didn't work (with the reason) |
| rejected / skipped / cancelled | Discarded · Skipped · Cancelled |
| Generated idea: new / saved / sent_to_studio / rejected / archived | To use · Saved · Used · Not for me · Archived |
| Research idea: proposed / shortlisted / selected / produced / rejected / saved | Suggested · Shortlisted · Being made · Made · Dropped · Saved |
| Job (stage) retrying | Shown as **Didn't work** with the error, because nothing resumes it automatically (C.3) |

## A.7 Safeguards kept exactly

* Owner-only access (RLS, `is_owner`) and session handling.
* Encrypted credentials, never shown beyond the last 4 characters.
* Approval before posting: by you, or by Auto Review & Post with all its checks and fix limits.
* Publish guards: approved post, account match, freshness, licences, one publication per post, 30-minute clash rule.
* X budget cap ($1).
* Job retries and backoff.
* Manual "post it yourself" tasks and "check on the platform" handling.
* Pause publishing.
* Telegram commands.
* Audit log, which is never cleared.
* Undo on clears.

---

# Part B — Required backend work: B1 "Create exactly the selected idea"

**Verified need.** Production today only runs as a batch. `produce_batch` picks the week's shortlisted
`content_ideas` per channel, up to the capacity plan, then marks them *produced*. No job takes one idea. The engine
already has the right building block, `produce_project(conn, router, storage, idea, week)`, which makes one idea's
package with resumable stages.

**Proposed change (engine and database; the dashboard calls it):**

1. **A new owner job `produce_idea`**, with input `{content_idea_id}` *or* `{generated_idea_id, channel}`.
   * Runs in the existing queue workflow (owner jobs). It goes through the Worker's dispatch like other owner jobs,
     so no Worker change is needed.
   * Respects the existing guards:
     * the `production` run lock (never runs alongside a batch);
     * the **paused** flag (it refuses with a clear message);
     * the brand overrides.
   * Steps:
     * a generated idea is first turned into a `content_ideas` row for that channel, using its title, summary as
       angle, the `source_id`s from its `trend_signals`, its score, and the current batch week;
     * `produce_project(...)` for that one idea;
     * `plan_distribution(week, channel)`, which creates its posts as *waiting for approval*;
     * `auto.run(...)` (a no-op while Auto Review & Post is OFF).
   * Reports progress labels per stage through the existing `jobs.progress`.
2. **Idempotent and resumable.** The job key is per idea, so pressing twice doesn't make two packages. Running it
   again after a failure resumes from the failed stage, because finished stages are skipped (existing `run_stage`
   behaviour). This is what powers "Try again from this step".
3. **Link back from generated ideas.** A small migration: `generated_ideas.content_idea_id`, nullable, so "Used"
   can link to the project that was made. It sets the generated idea's status to *sent to studio* as today.
4. **Owner permissions.** `produce_idea` is added to the allowed owner job types. The existing RLS insert policy
   (`requested_by = 'owner'`, status queued) already covers it.
5. **Scheduling, unchanged.** Posts get slots from the account schedules for the week after the batch week (today's
   rule). The Schedule step shows those slots and the owner can move them earlier in Calendar (existing). Filling
   *this* week's free slots would be a separate change; it isn't proposed.
6. **Tests:**
   * exactly one package for the chosen idea, and no other idea is produced;
   * a generated idea is converted with its sources;
   * a second press does nothing;
   * a failed stage resumes;
   * paused and locked runs are refused;
   * posts wait for approval, or go through Auto Review & Post when it's ON;
   * the weekly batch is unaffected.

**What stays separate:** "Make this week's videos" (batch) is unchanged and lives in Activity → Quick actions.

---

# Part C — Verification findings

## C.1 The AI failure (checked against the live data)

**Facts:**
* All 12 failed projects stopped at the **script** stage (22 attempts total):
  * 20 with *"All providers failed for research_summarizer"*;
  * 2 with *"No free AI provider available for role voice_editor"*.
* The research-summary job is assigned to 5 models. Each was unavailable for a different reason:

| Model assigned to research summary | What the live data shows | Kind of problem |
|---|---|---|
| Gemini 2.5 Flash / 3.8 Flash | 8 successful calls today, then **429 rate limited** at 17:57; the provider then rested until 18:14. Last key check: "free limit reached or the free plan isn't switched on" | Provider limit (free quota used up by today's idea and research runs) |
| NVIDIA nemotron-3-super | 404 "Function … not found for account". The NVIDIA **key works** (the key check used `z-ai/glm-5.3`); only this model isn't available to your account | Configuration (the model isn't offered to this account) |
| Cerebras zai-glm-4.7 | 404 "archived and unavailable" | Provider retired the model |
| Ollama deepseek-v4-pro | "not free on your plan"; resting until tomorrow | Provider plan |

* **Working services today:** Groq, Cloudflare, OpenRouter (it wrote scripts successfully at 18:03–18:06), LLM7,
  OVH and Aion. **None of them is assigned the research-summary job.**

**Conclusion:** configuration and provider availability, not a code defect. It can be fixed **without code**, in
today's AI APIs → *Models and the jobs they do*:
1. Tick **Evidence scout** (research summary) and **Voice editor** on a working model, for example Groq
   `openai/gpt-oss-120b` or OpenRouter `nvidia/nemotron-3-ultra-550b-a55b:free`.
2. Optionally untick NVIDIA's `nemotron-3-super` and Cerebras's `zai-glm-4.7`.
3. Gemini: check the free tier is switched on in Google AI Studio, or add a key from another person's own project.

Optional engine improvements (D.2) would make this self-healing, but they aren't required.

## C.2 Which proposed features really are front end only

| Feature | Data it needs | Checked | Front end only? |
|---|---|---|---|
| Content tabs | `content_projects.status` | All statuses exist | Yes |
| Project page tabs | Existing Review queries | Same as today | Yes |
| Project History | `generation_jobs.project_id` (stage jobs carry it), `auto_reviews.project_id`, `approvals.target_id` (project and post ids), `scheduled_posts` via `content_variants.project_id`, `published_posts`; `notifications` have **no project id**, only a `link` (auto-review messages link to `/review/<id>`; "week ready" doesn't) | Partly | Yes, with notifications shown only when their link names the project |
| Unified idea list | `generated_ideas` and `content_ideas` are separate tables with different columns and statuses; no link between them | Yes | Yes for showing and filtering both. **"Used → which project"** needs B1's link column |
| Real stage progress | Stage jobs per project: `script`, `package`, `render_preview` (one per video/Short), `thumbnails`; top-level `generation_jobs.progress` labels | Yes | Yes. Finer steps inside "script" (summary, writing, fact check) aren't reported today; the UI won't invent them |
| Home Needs you, Next posts, health | Existing queries | Yes | Yes |
| "Ready to create" check | Worker and database reachable (Setup status endpoint), last key check (`provider_check`) | Yes, but per provider, not per job | Yes as an approximation ("last key check"). An exact per-job readiness needs D.3 |
| Approval mode everywhere | `settings.auto_review_post` | Yes | Yes |
| Redirects incl. OAuth return | Dashboard routes; the Worker redirects to `/settings?connected=` | Yes | Yes |
| Telegram optional | Engine notifications already skip silently when not configured | Yes | Yes |
| Create package for one idea | — | No such job | **No: B1** |
| Post one post now | — | No such endpoint | **No: deferred (D.1)** |

## C.3 Real retries per stage (what the Progress screen may offer)

| Failed stage | Existing action | Complete? | With B1 |
|---|---|---|---|
| script | `regenerate_script` | **No**: it writes a script and preview but doesn't run the package stage (no Shorts or posts) | "Try again from this step" re-runs `produce_idea`, which resumes at script and then continues |
| package | none | — | Resumes at package |
| render_preview | `rerender_preview` | Yes | Same, or resume |
| thumbnails | `regenerate_thumbnails` | Yes | Same, or resume |
| facts expired (post blocked) | `recheck_project` | Yes | Unchanged |

**Also verified:** a stage marked *retrying* is never resumed automatically. The helper that would pick it up isn't
called anywhere, and the project is marked *failed* straight away. So today's "retrying" label is misleading; the UI
will show "Didn't work" with the reason (D.2 covers an optional fix).

---

# Part D — Deferred and optional (not part of the requested work)

| ID | Item | Status |
|---|---|---|
| **D.1 (was B3)** | One-click **Post now** for a single post | **Deferred.** Needs a backend endpoint or job that publishes one specific post through the normal publish guards. Not simulated by publishing everything due |
| D.2 | Self-healing AI routing: treat "model not found for this account" and "archived" as *model unavailable* so the catalog substitutes, and let a job fall back to any working model when every assigned one fails; resume or honestly mark *retrying* stages | Optional engine work. Not needed to fix C.1 |
| D.3 | Exact "ready to create" per job: the key check also reports which jobs have at least one working model | Optional engine work |
| D.4 | Fill this week's free slots for a single package (instead of next week's) | Optional, not proposed |

---

# Build order (once you say go)

1. **B1 backend** (`produce_idea`, link column, tests).
2. Navigation shell and every redirect (including OAuth returns).
3. Content and the project page.
4. Home.
5. Create flow on B1.
6. Activity with visible Quick actions.
7. Settings sections.
8. Help and tour.
9. Browser tests at laptop, short-screen and phone sizes, then push and deploy.

Before or alongside: apply the C.1 configuration fix in AI APIs, so production works while the rebuild happens.
