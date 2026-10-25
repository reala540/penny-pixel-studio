# How to run Penny & Pixel Studio

### A step-by-step guide, explained simply

Hi! This guide shows you how to switch on your own content studio. Do the steps **in order**. Each step says what to
click, what to copy, and how to check it worked.

You don't need to know how to code. You will mostly copy and paste.

> ⏱ One-time setup takes about **2–3 hours** (spread it over two days if you like).
> 🧑‍💻 After that, your weekly job is about **30–45 minutes on Monday**.

---

## First, a picture of how it works

Think of the studio as a little TV station with robot helpers:

| Helper | What it does | Where it lives |
|---|---|---|
| 🧠 **The Engine** | Finds news, writes scripts with free AI, records Penny's and Pixel's voices, makes videos and thumbnails, posts them | GitHub (it wakes up on a schedule) |
| 🗄 **The Memory** | Remembers every idea, script, video, post and setting | Supabase |
| 🖥 **The Dashboard** | The website where *you* watch, edit and approve | Vercel |
| 🛎 **The Doorbell** | Connects your accounts, listens to Telegram, wakes the Engine when a post is due | Cloudflare Worker |
| 📱 **The Messenger** | Sends you "your week is ready" and "posted ✅" messages | Telegram |

**The weekly rhythm:**
1. **Saturday:** the Engine researches ideas.
2. **Sunday:** it makes the videos. You get a Telegram message.
3. **Monday:** you check and approve them (30–45 minutes).
4. **All week:** approved posts go out by themselves.

Nothing is ever posted without your approval. Everything is free except X, which costs at most **$1 a month**, and only
if you choose to use it.

---

## The meet-the-hosts bit

| | Pixel | Penny |
|---|---|---|
| Channel | **Penny & Pixel AI** | **Penny & Pixel Money** |
| Talks about | AI tools, tech news, tutorials | Money, budgeting, careers, economics |
| Personality | Curious tinkerer who tests things | Calm friend who's good with numbers |
| Colours | Indigo and cyan | Forest green and gold |

Handles to try to claim (check they're free first): **@pennyandpixel** on X and TikTok, **Penny & Pixel** on Facebook,
**@PennyAndPixelAI** and **@PennyAndPixelMoney** on YouTube. If a name is taken, add "hq" or "tv" at the end and
change it in `config/brand.yaml`.

---

## Part A — Get your free accounts ready

### Step 1. Make the social accounts

Make these, all free:

1. **Two YouTube channels.** In YouTube, open your profile picture → *Settings* → *Add or manage your channels* →
   *Create a channel*, once for "Penny & Pixel AI" and once for "Penny & Pixel Money".
2. **A Facebook Page** called "Penny & Pixel". Use a Page, not a personal profile.
3. **A TikTok account** @pennyandpixel.
4. **An X account** @pennyandpixel.
5. **Telegram** on your phone.

✅ **Check:** you can see all five accounts when you sign in.

🔒 Turn on two-step login (2FA) on every account. It's in each app's security settings.

### Step 2. Make the free "helper" accounts

Sign up for these with the same email:

| Website | Why |
|---|---|
| [github.com](https://github.com) | Keeps the code and runs the Engine |
| [supabase.com](https://supabase.com) | The Memory. **Already done:** your project `penny-pixel-studio` exists |
| [cloudflare.com](https://dash.cloudflare.com/sign-up) | Hosts the Dashboard and the Doorbell |

---

## Part B — Put the code on GitHub

### Step 3. Your code repository

Your code lives in a **private** GitHub repository (a "repo" is a folder on GitHub).

- If Claude already pushed it for you, just open it on github.com.
- If not: on GitHub press **+** → **New repository** → name it `penny-pixel-studio` → choose **Private** → leave
  everything else empty → **Create**. Then ask Claude to push the code to it.

✅ **Check:** you can see folders called `engine`, `dashboard`, `worker`, `config` and this `GUIDE.md`.

---

## Part C — Connect the Memory (Supabase)

Your Supabase project **penny-pixel-studio** is already created: tables, security rules and performance indexes are
installed, and your brand, both channels, the five accounts, the AI provider list, the $1 X budget and default settings
are already loaded.

### Step 4. Copy four things from Supabase

Open [supabase.com/dashboard](https://supabase.com/dashboard) → project **penny-pixel-studio**.

1. Press **Connect** at the top → **Connection string** → choose **Session pooler**. Copy the address. It looks like
   `postgresql://postgres.eazmczmnunzrmrpsrhvx:[YOUR-PASSWORD]@aws-0-eu-central-1.pooler.supabase.com:5432/postgres`.
   Replace `[YOUR-PASSWORD]` with your database password. If you don't know it: *Project Settings → Database →
   Reset database password*. This whole line is your **SUPABASE_DB_URL**.
2. *Project Settings → API*:
   - **Project URL** → this is **SUPABASE_URL** (`https://eazmczmnunzrmrpsrhvx.supabase.co`)
   - **anon / public key** → this is **SUPABASE_ANON_KEY** (safe to share)
   - **service_role key** → this is **SUPABASE_SERVICE_ROLE_KEY**. ⚠️ This one is a master key. Never share it or put
     it in any website.

Keep these in a private note for the next steps.

### Step 5. Make your secret lock key

The studio locks your account logins with a secret key. Make one:

- **Windows:** open *PowerShell* and paste:
  ```powershell
  $b=New-Object byte[] 32;[Security.Cryptography.RNGCryptoServiceProvider]::Create().GetBytes($b);[Convert]::ToBase64String($b)
  ```
- **Mac or Linux:** open *Terminal* and paste: `openssl rand -base64 32`

You'll get something like `q3Z...9w=` (44 characters). That's your **TOKEN_ENCRYPTION_KEY**. Keep it secret, and don't
lose it: if you change it, you have to reconnect your accounts.

---

## Part D — Get the free AI and research keys

Each key is like a library card for a free service. You need **at least Gemini and Groq**. The others make the
writing better and give backups.

### Step 6. AI keys (about 15 minutes)

| Name to save it as | Where to get it | What to click |
|---|---|---|
| `GEMINI_API_KEY` | [aistudio.google.com/app/apikey](https://aistudio.google.com/app/apikey) | *Create API key* |
| `GROQ_API_KEY` | [console.groq.com/keys](https://console.groq.com/keys) | *Create API Key* |
| `NVIDIA_API_KEY` | [build.nvidia.com](https://build.nvidia.com) | Join the free Developer Program → *Get API Key* |
| `MISTRAL_API_KEY` | [console.mistral.ai/api-keys](https://console.mistral.ai/api-keys) | *Create new key* (free plan) |
| `OPENROUTER_API_KEY` | [openrouter.ai/keys](https://openrouter.ai/keys) | *Create Key* |
| `CLOUDFLARE_AI_TOKEN` | Cloudflare → *My Profile → API Tokens* → *Create Token* → template **Workers AI** | *Use template → Continue to summary → Create Token*, then copy the token |
| `CLOUDFLARE_ACCOUNT_ID` | Cloudflare home page → your account → **Account ID** (right side) | Copy the 32-character ID. Save this as its own secret |

Each row is **one** secret: one name, one value. Names have no spaces.

Optional extras (add later if you like): `AION_API_KEY`, `OLLAMA_API_KEY`, `ZAI_API_KEY`, `CEREBRAS_API_KEY`,
`SAMBANOVA_API_KEY`. See `docs/PROVIDERS_AND_LIMITS.md`. These start switched off; switch them on in
Dashboard → Settings → AI writers.

### Step 7. Research and picture keys (about 10 minutes)

| Name | Where | Why |
|---|---|---|
| `PIXABAY_API_KEY` | [pixabay.com/api/docs](https://pixabay.com/api/docs/): sign up free, log in, and the key is in the green box on that page | Free photos (license saved automatically) |
| `FRED_API_KEY` | [fredaccount.stlouisfed.org/apikeys](https://fredaccount.stlouisfed.org/apikeys) → **+ Request API Key** → write one line ("Personal finance explainer videos"), tick the terms box, then submit | Real economic numbers for Penny |
| `YOUTUBE_API_KEY` | See **Step 7a** below | See what's popular |
| `PEXELS_API_KEY` *(skip for now)* | Pexels paused new keys in Sept 2026. If they reopen, get one at [pexels.com/api](https://www.pexels.com/api/) | Extra photos |
| `SEC_USER_AGENT` | Just type your name and email, like `Penny Pixel Studio you@example.com` | Required politeness for company filings |

No photo keys at all? That's fine. The studio also searches **Openverse** (free, no key, public-domain photos
only), and if nothing fits it makes its own original picture cards.

### Step 7a. Get the YouTube API key (about 5 minutes)

1. Go to [console.cloud.google.com](https://console.cloud.google.com) and sign in with the Google account that owns
   your channels.
2. Top bar → project picker → **New Project** → name it `penny-pixel-studio` → **Create**. Make sure it's selected.
   (If you already made this project for the YouTube login in Part G, use the same one.)
3. Left menu → **APIs & Services → Library** → search **YouTube Data API v3** → open it → **Enable**.
4. Left menu → **APIs & Services → Credentials** → **+ Create credentials → API key**. Copy the key it shows.
5. Click **Edit API key** (or the key's name):
   - Under **API restrictions** choose **Restrict key** → tick only **YouTube Data API v3**.
   - Leave **Application restrictions** on **None** (GitHub's computers change address).
   - **Save**.
6. Save it as the GitHub secret `YOUTUBE_API_KEY`.

It's free: 10,000 "units" a day. Each search costs 100, and the studio uses about 10–20 a week.

---

## Part E — Give the Engine its keys (GitHub secrets)

### Step 8. Save everything as GitHub secrets

On GitHub, open your repo → **Settings** → **Secrets and variables** → **Actions**.

1. Press **New repository secret** for each of these (name on the left, value on the right):
   - `SUPABASE_DB_URL`, `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `SUPABASE_ANON_KEY`
   - `TOKEN_ENCRYPTION_KEY`
   - every AI and research key from steps 6 and 7
2. Open the **Variables** tab → **New repository variable**:
   - Name `DASHBOARD_URL`, value `https://dashboard-beta-ten-13.vercel.app` (your live dashboard).
     back and fix it if it's different.

✅ **Check:** the Secrets list shows the names (GitHub never shows the values again, which is normal).

### Step 9. GitHub spending stop (only needed for a private repo)

**Public repo:** skip this. GitHub Actions is free and unlimited for public repos on the standard runners
(`ubuntu-latest`), which is all the studio uses. Do check that https://github.com/settings/billing shows no warning
or lock, because a locked account can't run any workflow, even on a public repo.

**Private repo:** GitHub → your profile picture → **Settings** → **Billing and licensing** → **Budgets and alerts**.
Make sure Actions has a **$0 budget** with **"Stop usage when budget limit is reached"** ticked. Then GitHub can never
charge you; the studio just pauses if the 2,000 free minutes a month run out.

---

## Part F — Switch on the Engine

### Step 10. Run "First-time setup"

GitHub → your repo → **Actions** tab → **First-time setup** → **Run workflow** → **Run workflow**.

It takes about 5–10 minutes. It:
1. finishes the database setup,
2. loads the brand, channels and AI providers,
3. makes **two channel trailers** ("Meet Pixel" and "Meet Penny") for you to review,
4. tests which AI keys work. Open the run, click the job, and expand **studio providers**: each provider says `ok`,
   `no key` or `failed`.

✅ **Check:** a green tick ✔. If you see a red ✖, open it and read the last lines; usually a secret is missing or
mistyped.

### Step 11. Measure your speed (Benchmark)

Actions → **Benchmark** → **Run workflow**. When it finishes, the summary says whether the full plan (6 long videos +
12 Shorts a week) fits GitHub's free minutes. If it says it may not fit, the studio automatically makes fewer videos
and tells you. To make more, see "Extra free power" at the end.

---

## Part G — Your Dashboard is already online (Vercel)

### Step 12. Open your dashboard

**Already done for you:** the dashboard is live on Vercel at
**https://dashboard-beta-ten-13.vercel.app** (Vercel project `dashboard`, linked to your GitHub repo). Every push to
`main` updates it automatically. Its Supabase settings (`VITE_SUPABASE_URL` and `VITE_SUPABASE_ANON_KEY`) are already
saved in Vercel → project **dashboard** → **Settings → Environment Variables**.

> ℹ️ Vercel's free Hobby plan is meant for non-commercial use. While you're starting out that's fine. When the
> channels start earning money, either upgrade Vercel or move the dashboard to Cloudflare Pages (free for commercial
> use): Cloudflare → Workers & Pages → Create → Pages → connect the repo, root directory `dashboard`, build command
> `npm ci && npm run build`, output `dist`, and the same two environment variables.

✅ **Check:** open the link. You see the Penny & Pixel sign-in page. Your privacy page is at
https://dashboard-beta-ten-13.vercel.app/privacy and terms at https://dashboard-beta-ten-13.vercel.app/terms.

### Step 13. Make yourself the owner

1. Open your dashboard link. Press **First time? Create the owner account**. Use your email and a long password.
2. Click the link in the confirmation email, then sign in.
3. **Now lock the door:** Supabase → **Authentication** → **Sign In / Providers** → turn **off** "Allow new users to
   sign up".
4. Also in Supabase → **Authentication → URL Configuration**: set **Site URL** to `https://dashboard-beta-ten-13.vercel.app`
   and add the same address under **Redirect URLs**. (Do this *before* step 1, so the confirmation email links to your
   dashboard.)

The first person to sign in becomes the owner, and the database refuses everyone after that. That's why you do step 3
right away.

✅ **Check:** you land on **Home**. Under **Needs you** the two channel trailers are waiting for review. Before connecting anything, you can explore `/demo`; its sample activity is clearly labelled and never changes your studio.

---

## Part H — Switch on the Doorbell (Cloudflare Worker) and Telegram

### Step 14. Make the Telegram bot

1. In Telegram, search for **@BotFather** → send `/newbot` → name it "Penny & Pixel Studio" → pick a username ending in
   `bot`.
2. BotFather gives you a token like `123456:ABC...`. That's **TELEGRAM_BOT_TOKEN**.
3. Make up a long random password using **only letters and numbers** (no spaces, no symbols like `! @ # $ .`), for example
   `PennyPixelHook2026x8842`. Telegram refuses anything else. That's **TELEGRAM_WEBHOOK_SECRET**.

### Step 15. Make two tokens for the Doorbell

1. **Cloudflare token:** Cloudflare → *My Profile → API Tokens → Create Token* → template **Edit Cloudflare Workers** →
   create. Save it as **CLOUDFLARE_API_TOKEN**.
2. **GitHub token** (so the Doorbell can wake the Engine): GitHub → *Settings → Developer settings → Personal access
   tokens → Fine-grained tokens → Generate new token*:
   - Repository access: **Only select repositories** → `penny-pixel-studio`
   - Permissions → **Actions: Read and write**
   - Save it as **WORKER_GITHUB_TOKEN**.

### Step 16. Deploy the Doorbell

1. Add the new secrets to GitHub (step 8 again): `TELEGRAM_BOT_TOKEN`, `TELEGRAM_WEBHOOK_SECRET`,
   `CLOUDFLARE_API_TOKEN`, `WORKER_GITHUB_TOKEN`, and `CLOUDFLARE_ACCOUNT_ID` (if not already added).
2. Actions → **Deploy Worker (Cloudflare)** → **Run workflow**.
3. When it's green, open the run: the summary shows **Your Worker address**, like
   `https://penny-pixel-studio.yourname.workers.dev`.
4. Vercel → project **dashboard** → **Settings → Environment Variables** → add `VITE_WORKER_URL` with that address
   (all environments) → **Deployments** → newest one → **⋯ → Redeploy**.

### Step 17. Link Telegram

Dashboard → **Settings → Telegram** → **Get a link code**. In Telegram, open your bot and send `/link CODE` (use the code
shown). The bot replies "Linked!".

✅ **Check:** send `/status` to your bot. It answers with your studio status.

---

## Part I — Connect your social accounts

Each platform needs a free "developer app" so the studio is allowed to post for you. Do them one at a time. In every
case, the **redirect address** (also called callback URL) is your Worker address plus a path:

| Platform | Redirect address to paste |
|---|---|
| YouTube (Google) | `https://YOUR-WORKER/oauth/youtube/callback` |
| Facebook | `https://YOUR-WORKER/oauth/facebook/callback` |
| TikTok | `https://YOUR-WORKER/oauth/tiktok/callback` |
| X | `https://YOUR-WORKER/oauth/x/callback` |

After each one, add its keys as GitHub secrets, run **Deploy Worker** again, then go to Dashboard → **Settings →
Accounts** → **Connect**.

### Step 18. YouTube (both channels)

1. [console.cloud.google.com](https://console.cloud.google.com) → create a project "Penny Pixel Studio".
2. *APIs & Services → Library* → enable **YouTube Data API v3** and **YouTube Analytics API**.
3. *OAuth consent screen* → External → fill in the app name and your email, and paste your privacy
   (`https://YOUR-DASHBOARD/privacy`) and terms (`https://YOUR-DASHBOARD/terms`) links. Add scopes `youtube.upload`,
   `youtube.readonly` and `yt-analytics.readonly` (views, watch time and retention for the weekly report).
4. ⚠️ **Important:** press **Publish app** to move it from *Testing* to **In production**. In testing mode Google
   logins expire every 7 days. (You'll see an "unverified app" warning when you sign in; that's OK because it's your
   own app. Click *Advanced → Go to app*.)
5. *Credentials → Create credentials → OAuth client ID* → **Web application** → add the YouTube redirect address →
   create. Save **GOOGLE_CLIENT_ID** and **GOOGLE_CLIENT_SECRET** as GitHub secrets.
6. Run **Deploy Worker**, then in the Dashboard press **Connect** next to *YouTube AI*. When Google asks, pick the
   **Penny & Pixel AI** channel. Repeat for *YouTube Money* and pick the Money channel.

📌 **Until Google audits your app, uploads arrive as Private.** The studio tells you, and you press Public (or
Schedule) in YouTube Studio; it takes 10 seconds. When you want full automation, apply for the YouTube API audit
([form](https://support.google.com/youtube/contact/yt_api_form)). Your privacy policy is at
`https://YOUR-DASHBOARD/privacy` and your terms at `https://YOUR-DASHBOARD/terms`; both are already built in.
When approved, change `api_audited: false` to `true` in `config/services.yaml`.

### Step 19. Facebook Page

1. [developers.facebook.com](https://developers.facebook.com) → *My Apps → Create App* → type **Business**.
2. Add **Facebook Login for Business**. In its settings, add the Facebook redirect address.
3. *App settings → Basic*: copy **App ID** → `FACEBOOK_APP_ID`, **App secret** → `FACEBOOK_APP_SECRET`.
4. Run **Deploy Worker** → Dashboard → **Connect** next to *Facebook Page* → allow access to your Penny & Pixel Page.

While the app is in development mode it works for Pages you manage, which is all you need.

### Step 20. TikTok

1. [developers.tiktok.com](https://developers.tiktok.com) → *Manage apps → Connect an app*.
2. Add products **Login Kit** and **Content Posting API**. Add the TikTok redirect address, plus your privacy and terms
   links. Scopes:
   `user.info.basic`, `video.upload`, `video.publish`.
3. Copy **Client key** → `TIKTOK_CLIENT_KEY`, **Client secret** → `TIKTOK_CLIENT_SECRET`.
4. Run **Deploy Worker** → Dashboard → **Connect** next to *TikTok*.

📌 **Until TikTok audits your app, videos arrive in your TikTok inbox as drafts.** Open TikTok, tap the notification,
and post. To apply for direct posting, submit the app for review in the TikTok developer portal. When approved, set
`direct_post_approved: true` in `config/services.yaml`.

### Step 21. X (optional, max $1 a month)

1. [developer.x.com](https://developer.x.com) → create a Project and App → *User authentication settings* → **OAuth
   2.0**, type **Web App**, add the X redirect address, permissions **Read and write**.
2. Copy **Client ID** → `X_CLIENT_ID`, **Client Secret** → `X_CLIENT_SECRET`.
3. X now charges per post (around $0.015). Before buying credits, **check the smallest amount X lets you buy**; it may
   be more than $1 even though the studio only spends about $0.20 a month. In the X developer console, **set a
   spending limit too**.
4. Run **Deploy Worker** → Dashboard → **Connect** next to *X*.

Don't want to pay at all? Skip this step. X posts then become "Post it yourself" quick jobs with the text ready to copy.

✅ **Check:** Dashboard → Settings → Accounts shows **Connected** for each account.

---

## Part J — Your first real week

### Step 22. Approve the trailers

Dashboard → **Content → Needs you**. Open "Meet Pixel" and "Meet Penny", watch them, choose a thumbnail, then press **Approve package**. They
go out at their scheduled times. Make them your first videos.

### Step 23. Start the first batch now (instead of waiting for Saturday)

Dashboard → **Create**: choose a channel, choose or generate an idea, check its sources, then press **Create package**. Only that idea is made, and the page shows each real step as it happens. To make the whole week's batch instead, use **Activity → Quick actions → Make this week's videos (batch)**. Production can take a while on free services; the page (and Telegram, if linked) tells you when the package is ready. With Auto Review & Post OFF nothing is approved or posted until you approve it.

---

## Part J2 — Ideas, themes and extra keys (new in v2.3)

### Step 24. Let the AI find ideas for you

1. Open **Mission** (the first page). Under *Direct the studio* you'll see **AI Idea Generator**.
2. Press **Generate 10 Ideas**. After about 5–10 minutes, 10 ideas appear, best first.
3. Each idea has a score out of 100. **70 points come from real, dated sources** (Google Trends, news, Hacker News,
   official feeds…). Press **Why this score** to see the sources with their dates and links. An idea with no current
   source says **Trend unverified**: fine for an evergreen video, but it isn't news.
4. Like one? Press **Send to Studio**. The objective box fills in for you. Read it, change anything, then
   **Launch mission**, or press **Create from this idea** to make just that one. Nothing is posted until you approve it in Content.
5. **Save** the ones you might use later, **Reject** the ones you never want suggested again, or **Refine** one with
   a note like "make it practical for students in Kenya". All of them live in **Content → Ideas**.
6. Want ideas automatically? **Settings → Automation → Generate ideas → Every day** (or chosen days) and pick an
   hour. **Settings → Idea generation** sets regions, categories, language and which sources to use.

### Step 25. Light or dark

Click the sun, moon or screen icon at the bottom of the menu (or the top bar on a phone), or **Settings →
Appearance**. *Screen* means "follow my phone or computer".

### Step 26. More than one key per AI service (optional)

1. Open **AI APIs** in the menu → **Add an API key**.
2. Choose the service (for example `gemini`), give it a label (`Gemini · Sam`), say whose key it is and what they
   allowed it for, paste the key and tick the authorisation box.
3. Tick **separate account with its own allowance** only if the key really belongs to a different account with its
   own limits, used within that account's rules. Keys from the same account share one limit, and services like
   Google and Groq don't allow extra accounts to get around free limits, so the studio won't switch between those
   keys to dodge a limit.
4. Press **Test** to check it. Use **Limits** for a daily cap, parallel requests and, for paid services, prices and a
   monthly cap.
5. **How keys share the work** (at the top of each service) picks the strategy: priority, round robin, least used,
   healthiest, or weighted percentages.

### Step 27. Auto Review & Post (optional, starts OFF)

**OFF** (the normal setting): you approve every package yourself, exactly as in Part K.

**ON**: the AI checks each finished package (quality, every fact sourced, facts still fresh, the right accounts, the
money disclaimer, licensed photos, and an independent AI policy review that must be at least 85% confident). If
everything passes, it approves the package and it posts at its normal times. If anything fails, it waits for you and
Telegram tells you why.

* Switch it in **Settings → Automation** (it asks you to confirm), or in Telegram with `/autopost on confirm`.
* Switch it off with the same switch or `/autopost off`. Posts that haven't gone out yet come back to Review.
* The menu always shows **Auto Review & Post: ON/OFF**, and Telegram's `/status` shows it too.
* **When a check fails, the studio fixes it and tries again** (new in v2.5). It repairs only the part that failed
  (post text, the script, the facts or a photo) and runs every check again, up to 3 times. You can change the number
  (0–5) in **Settings → Automation**. If it passes, it posts at the next free time on that account's schedule. A wrong
  account or a policy concern is never retried; anything still failing comes to you on Telegram.

---

## Part J3 — Easier to run (new in v2.5)

### Step 28. The Setup page

Open **Settings → Getting started** (old `/setup` links still work). Every step tests itself and shows ✅ when it works: the basics, Telegram, AI keys,
YouTube, Facebook, TikTok, X, research keys, your posting schedule and your first video. A bar at the top shows how
far you are, and you can stop and continue any time.

* **Paste values on the Setup page instead of GitHub.** Press **Save & test**: the value is encrypted on the server,
  the page only ever shows the last 4 characters, and the studio checks it with the real service straight away.
* Each platform step shows the exact **redirect address** to paste on the platform's website, with a **Copy** button.
* **Don't delete anything from GitHub.** Values already in GitHub keep working. A value saved on the Setup page wins
  over the GitHub one. Once a value is saved there, Setup shows *Also in GitHub: safe to remove there*; removing it is
  optional.
* **These must always stay in GitHub:** `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `SUPABASE_ANON_KEY`,
  `SUPABASE_DB_URL`, `TOKEN_ENCRYPTION_KEY`, `CLOUDFLARE_API_TOKEN`, `CLOUDFLARE_ACCOUNT_ID`, `WORKER_GITHUB_TOKEN` and the
  `DASHBOARD_URL` variable. The studio needs them before it can reach its own database.

### Step 29. See what's running: the Activity page

**Activity** shows what the studio is doing right now (with progress, e.g. "Step 3 of 5: removing duplicates"),
today's numbers, the six steps of the studio (Ideas → Research → Write → Check → Review → Post) and a timeline of
everything in plain words. **Problems** filters to what went wrong, and each problem has a button that takes you to the
fix. The line at the bottom of the menu always says whether the studio is working or idle.

### Step 30. Your posting schedule

**Settings → Posting schedule**: for each account choose the days, the times (up to 4 a day), how many posts of each
type per week, or pause the account. The preview shows the week before you save, and it warns you if the posts don't
fit the days you chose, two posts are less than an hour apart, or YouTube's daily upload limit would be passed.
Changes apply from the next production run; tick *Also move posts already waiting* to move planned posts too.
**Reset to default** puts back the schedule from `config/accounts.yaml`.

### Step 31. Clear buttons

Most lists have a **Clear** button: the objective and the idea batch in Activity → Technical details, finished jobs, this week's
problems, the activity history, old research, rejected drafts in Content → Not used, new ideas, idea history, AI usage numbers
and errors, and the automatic review log. Calendar has **Cancel this post** and every package page has **Discard package**.
Clear always asks first, and most clears have **Undo** for a few seconds. Published posts and the audit log can never
be cleared.

### Step 32. The tour

A 5-step tour appears the first time you sign in; replay it from **Help**. A small **?** next to a technical word
explains it.

## Part J4 — Five pages (new in v2.6)

The menu now has five pages, the same on a computer and a phone:

| Page | What it's for |
|---|---|
| **Home** | What needs you (packages to review, problems, reconnects, quick jobs), what's being made, the next posts, this week |
| **Create** | Make one package step by step: channel → idea → sources → **Create package** → real progress |
| **Content** | Every package by status (Needs you, In progress, Approved & scheduled, Published, Not used, All) and **Ideas** |
| **Calendar** | When each post goes out |
| **Activity** | What happened, **Quick actions** (batch, research, publish due posts), and **Technical details** (AI calls and jobs) |

**Settings**, **Help**, the theme and **Sign out** are at the bottom of the menu (on a phone: **More**). The menu always
says who approves: *You approve* or *Auto Review & Post*.

* **Create package makes only the idea you chose.** Planning posts and the automatic review touch only that package;
  your weekly batch and other packages are unchanged. Pressing it twice, or from two tabs, still makes one package.
  If a step fails, **Try again from this step** continues where it stopped; finished steps and planned posts aren't
  made twice.
* **Pause publishing doesn't stop making content.** While paused, Create still works and nothing is posted. (The
  scheduled weekly batch still skips its run while paused, as before.)
* **AI key check.** Settings → AI services & keys shows when the keys were last checked. Results older than a day may be
  out of date: press **Test again**. One working service doesn't mean every job is covered; the page names any job no
  passing service does.
* **Telegram is recommended, not required.** Without it, Home shows what needs you.
* **Old links keep working**: `/review`, `/library`, `/ideas`, `/research`, `/mission`, `/setup`, `/api`, `/week` and
  the platform sign-in returns all open the right new page.

---

## Part K — Your weekly routine (Monday, 30–45 minutes)

1. **Open the Telegram message** "Your week is ready" → tap **Open dashboard**.
2. **Content → Needs you**: for each package,
   - watch the preview,
   - read the box at the top: green means it passed every check; red means *check before approving* and says why,
   - look at **Sources & checks**: every fact shows its source link,
   - pick a **Thumbnail**,
   - check the **Posts** text for each account,
   - press **Approve package**, or **Rewrite with a note** (e.g. "make the opening more personal"), or **Discard package**.
3. Short on time? **Approve all that passed every check** approves only the green ones.
4. Look at **Home → Needs you** for quick jobs (e.g. "set this YouTube video to Public"), do them, press **Done**.
5. Reply to comments yourself on each app. Telegram gives you the links when posts go out.

**Handy Telegram commands:** `/status`, `/week`, `/review`, `/failed`, `/budget`, `/pause`, `/resume confirm`, `/autopost` (`on confirm` / `off`).

---

## What the words in the dashboard mean

| You see | It means | What to do |
|---|---|---|
| Ready for review | Passed every automatic check | Watch and approve |
| Needs a look | A check found something (it says what) | Fix the text, rewrite with a note, or approve anyway if you're sure |
| Waiting for approval | Planned, but you haven't approved it | Approve its package |
| Scheduled | Approved; it will go out by itself | Nothing |
| Post it yourself | The platform didn't allow automatic posting | Download, post, press **Done** |
| Check on the platform | An upload was interrupted | Look on the platform first. If it's there, press **Done**; if not, **Try again** |
| Blocked | Usually the facts are too old now | Calendar → **Re-check the facts**, or reject |
| Reconnect needed | A login expired | Settings → Accounts → **Reconnect** |

---

## If something goes wrong

| Problem | Fix |
|---|---|
| The dashboard says "Almost there" | `VITE_SUPABASE_URL` / `VITE_SUPABASE_ANON_KEY` are missing in Vercel. Add them and redeploy |
| "This studio already has an owner" | You signed in with a different email than the owner. Sign out and use the owner email |
| Connect buttons are grey | `VITE_WORKER_URL` is not set in Vercel (step 16.4) |
| Vercel says a deployment is "Blocked" | On the free plan the commit author must be you. Commit with your GitHub account (atonymutembei@gmail.com) |
| A GitHub run is red | Open it → read the last red lines. Most often a secret name is misspelled |
| "No free AI provider available" | Your AI keys are missing or used up for today. Add more keys (step 6) or wait until tomorrow |
| No Telegram messages | Setup → Telegram: paste the bot token and press **Save & test**, then get a link code and send `/link` again |
| Not sure what failed | Activity → **Problems**: each problem has a button to the fix |
| Nothing posted at the posting time | Is publishing paused (red bar at the top)? Is the Worker deployed? Is the post *Scheduled* (approved)? |
| YouTube says private | Normal until the Google audit (step 18) |
| Storage almost full | Daily maintenance deletes old previews. You can also delete old ones in Supabase → Storage |

---

## Extra free power (optional)

If the Benchmark says you need more minutes, use your own computer as a free GitHub "runner": repo → **Settings →
Actions → Runners → New self-hosted runner** and follow the commands. Then change `runs-on: ubuntu-latest` to
`runs-on: self-hosted` in `.github/workflows/weekly-produce.yml`. Your computer must be on during Sunday production.

---

## Changing things later

| Want to change | Where |
|---|---|
| How Penny or Pixel sound | Dashboard → Settings → Channel voices |
| Posting days and times | Dashboard → Settings → Posting schedule |
| Words the writers must never use | `config/brand.yaml` → `banned_phrases` |
| Which AI services to use | Dashboard → Settings → AI writers, or `config/providers.yaml` |
| Research sources | `config/research.yaml` |
| X monthly limit (max $1) | Dashboard → Settings → Budget |
| Timezone | Dashboard → Settings → Timezone |
| Keys and logins (Telegram, platforms, research) | Dashboard → Setup |

Edit files on GitHub by opening the file and pressing the ✏️ pencil, then **Commit changes**.

---

## The honest small print

- AI can still make mistakes. That's why every fact needs a source, a second AI checks it, the code double-checks the
  numbers, and **you** approve everything.
- YouTube monetization isn't guaranteed. The studio is built to make original, researched content (not copy-paste), which
  is what YouTube's rules ask for.
- Free tiers can change. If a provider stops being free, switch it off in Settings; the studio never moves to a paid
  plan by itself.
- Keep your `SUPABASE_SERVICE_ROLE_KEY`, `TOKEN_ENCRYPTION_KEY` and every token secret. If one leaks, make a new one,
  update it in GitHub, and run **Deploy Worker** again.

🎉 That's it. Welcome to your studio!
