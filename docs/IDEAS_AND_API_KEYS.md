# AI Idea Generator, themes and the AI API Manager (v2.3)

## AI Idea Generator

**Where:** Mission Control → *AI Idea Generator* (button **Generate 10 Ideas**), and the **Ideas** page (Idea Library).

**What happens when you press it**
1. A `generate_ideas` owner job is queued (one at a time: the button is locked while a batch is pending, and the
   engine takes a database lock, so two batches never run together).
2. The engine fetches fresh research from the sources you allowed (Settings → Idea generation), using your region,
   language and categories. Sources that fail are listed in the run's notes; the rest still count.
3. It builds an evidence pool: stored sources from the last 14 days.
4. A model proposes ideas and must cite evidence ids. Citations that don't match a stored source are dropped.
5. Duplicates are removed: within the batch (text similarity, or ≥3 shared title words covering 60% of the shorter
   title, or meaning via a free embeddings model when one is available) and against ideas, videos and rejected ideas
   from the last 120–180 days.
6. A **different** provider assesses originality, international relevance, feasibility and engagement (0–10 each)
   and flags sensitive, controversial or poorly supported topics.
7. Scores are combined, categories are kept varied (about a third at most from one category) and the top N are saved.

**Score (out of 100)**

| Criterion | Weight | Where it comes from |
|---|---:|---|
| Current trends and emerging opportunities | 70 | **Measured in code** from the cited stored sources: number of independent sources, how recent the newest is, signal strength (a Google Trends daily trend is strongest), and number of different source types |
| Originality | 10 | AI assessment, reduced when the idea resembles earlier ones |
| International relevance | 10 | AI assessment |
| Production feasibility | 5 | AI assessment |
| Engagement potential | 5 | AI assessment |

An idea with no valid, recent evidence gets **0/70 for trend** and is labelled **Trend unverified**. The AI never
supplies trend numbers; the evidence panel shows only what the source itself recorded (for example
"Google Trends daily trending search in US, approx. traffic 200K+" or "Hacker News: 640 points, 210 comments") with
its publication date and link. The 30% assessment is labelled as an opinion, not a measurement or a probability of
success.

**Confidence:** *high* = 3+ independent sources across 2+ source types, newest ≤ 7 days; *medium* = 2+ sources, or
one very fresh strong signal; *low* = weaker evidence; *unverified* = none.

**Actions on each idea:** Send to Studio · Save · Refine (with a note; evidence is kept) · Reject (never suggested
again) · Restore · Archive · Why this score.

**Send to Studio** builds a complete objective (title, summary, audience, markets, creative direction, dated evidence
links, care notes and the approval requirement) and places it in *Direct the studio* for you to edit. Launching it
queues research (or research + review package); the mission still stops at review and nothing publishes without
your approval.

**Automation** (Settings → Automation): manual, daily, weekly or chosen days, at an hour in the studio timezone.
The Worker's 15-minute check creates at most one job per day slot (`ideas:auto:YYYY-MM-DD`, unique in the database),
so a schedule can't run twice. Optional Telegram message when a batch is ready.

**When something is missing:** if no provider passed the last key check the panel shows *Configuration required*;
if no research is available every idea is marked *Trend unverified*; if fewer than N ideas pass the checks the run
is marked *partial* and says why.

## Themes

Light, Dark or System, in the sidebar (and the mobile header) and in Settings → Appearance. The choice applies
instantly, is remembered on this device (`localStorage`), and is applied by a tiny script in `index.html` before the
page draws, so there's no flash. *System* follows the device setting live. All colours come from CSS variables
(`--bg`, `--surface`, `--ink`, … and `--cr-*` for Mission Control) with light and dark values.

## AI API Manager

**Where:** **AI APIs** in the menu.

**Keys.** Add as many keys per provider as you have authorised: label, owner, what they allowed it for, optional
priority and daily limit. The key goes once to the Worker, which encrypts it (AES-256-GCM with
`TOKEN_ENCRYPTION_KEY`) into a table the browser can't read. The page only ever shows `••••` + the last 4 characters.
You can test, replace, disable or remove a key; removing deletes the encrypted key. The GitHub-secret key of each
built-in provider still works and counts as one key (it can be switched off per provider).

**Several keys from different people (v2.5).** Each provider card shows a label based on what its terms say:
*Add more keys* (Gemini, Cloudflare, Z.ai, Cerebras, SambaNova), *One key only* (Groq: its usage policy reportedly
bans using several accounts to go over its limits), *Borrowed keys not allowed* (NVIDIA: the trial is for testing,
not publishing; Mistral: its terms ban sharing keys) and *Check the owner's terms* for the rest. The labels guide;
they don't block anything. This is general information from the providers' published terms, not legal advice.

**How keys share the work** (per provider): Priority, Round robin, Least utilised, Health, Weighted (percentages).

**Limits per key:** requests/day, tokens/day, parallel requests, and a monthly spend cap that uses the prices you
enter (cost is an **estimate**: tokens × your prices). Keys over a limit are skipped; if none is left the router
moves to another provider, or reports clearly that no eligible key is available.

**Failover rules**
- Network errors, timeouts, 5xx and 408: retried on the same key up to *Retries on temporary errors* (default 2) with
  exponential backoff and full jitter, then the next key.
- 401/403: that key is marked *invalid* and the next key is tried.
- 429: `Retry-After` is honoured. The key's **whole quota group** rests and only keys in a different group are tried;
  otherwise the router moves to another provider. Keys are in the provider's group unless you tick
  *separate account with its own allowance* when adding them. Keys from the same account or project share one rate
  limit, and providers such as Google and Groq don't allow extra accounts to get around free limits: the studio never
  rotates keys to evade a quota.
- 402: that quota group is out of allowance for 24 hours.
- Any other 4xx: the request itself is wrong; no retry.
- Every request has a timeout (per provider). Nothing retries forever.

**Parallel work.** Brainstorming asks several providers at once (each request goes to exactly one provider: no
duplicate billable calls), limited by each key's and provider's parallel-request settings.

**Provider fallback.** When a provider can't answer, the next provider that offers a model for the same job (role) is
used; structured outputs are validated and repaired the same way. Substitutions are recorded and shown (for example
in an idea run's notes, and as failed calls in Mission Control).

**Models and jobs.** Each model's jobs (scriptwriter, critic, claim checker, …) can be changed; your changes survive
config syncs. *Test* lists the models a key can access.

**Monitoring.** Per key: health, calls today/this month, failures, rate-limit events, average latency, tokens,
estimated cost, last success, last error. Everything is **observed** by the studio from its own calls or
**estimated** from your prices; providers don't report usage or bills to the studio.

**Other providers.** *Add another provider* registers any OpenAI-compatible API (public https only). It starts
switched off and is only used if you confirm its terms allow monetised content. Paid providers cost money: set a
monthly cap and prices on each key.

## Reference

| Item | Value |
|---|---|
| Migration | `20261024000006_ideas_and_credentials.sql` |
| New tables | `ai_credentials`, `ai_credential_secrets` (no client access), `idea_runs`, `generated_ideas` |
| New columns | `ai_providers.key_strategy/max_concurrency/request_timeout_s/max_retries/use_env_key`, `provider_usage.credential_id/cost_source`, `ai_model_configs.roles_custom` |
| Settings keys | `idea_generator` (config and schedule), `ai_quota_rests` (engine-managed) |
| Owner jobs | `generate_ideas`, `refine_idea` |
| Worker endpoints (owner only) | `POST /api/credentials/add`, `/replace`, `/delete`, `/test`, `POST /api/providers/add` |
| Worker variable | `CLOUDFLARE_ACCOUNT_ID` (set by *Deploy Worker*, only to test Workers AI keys) |
| CLI | `studio ideas [--count N]` |
