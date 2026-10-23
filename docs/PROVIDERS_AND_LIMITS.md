# Free providers and limits (appendix)

This is the original 14-provider map, now the *starting configuration* in `config/providers.yaml`.
Free tiers change often: the numbers below were taken from the community lists
[mnfst/awesome-free-llm-apis](https://github.com/mnfst/awesome-free-llm-apis) (verified 5 Oct 2026) and
[open-free-llm-api/awesome-freellm-apis](https://github.com/open-free-llm-api/awesome-freellm-apis). Check each
provider's site before relying on them, and edit the YAML when they change. The router reads limits from config, so no
code change is needed.

## AI writers

| Provider | Tier | Enabled by default | Models (roles) | Free limit used in config | Key |
|---|---|---|---|---|---|
| Google Gemini | 1 | yes | 2.5 Pro (judge, writer), 2.5 Flash (fact sheet, writer, critic, repurposer), embeddings | 50 / 1,000 requests a day | `GEMINI_API_KEY` |
| Groq | 1 | yes | gpt-oss-120b (brainstorm, critic, repurposer, checker), Kimi K2 (brainstorm, voice) | ~1,000 a day | `GROQ_API_KEY` |
| NVIDIA NIM | 1 | yes | GLM-5.2 (checker, judge), Nemotron 3 Super (brainstorm, critic) | 40/min (config: 2,000 a day) | `NVIDIA_API_KEY` |
| Mistral | 1 | yes | Medium (voice editor), Large (writer) | free mode credits | `MISTRAL_API_KEY` |
| Cloudflare Workers AI | 1 | yes | Llama 3.3 70B (repurposer), bge embeddings | 10,000 neurons a day (shared) | `CLOUDFLARE_AI_TOKEN` + `CLOUDFLARE_ACCOUNT_ID` |
| OpenRouter | 1 | yes | Nemotron 3 Ultra :free, Gemma 4 :free | 50 a day per free model | `OPENROUTER_API_KEY` |
| Aion Labs | 2 | no | Aion 3.0 (story hooks) | 20K tokens a day | `AION_API_KEY` |
| Ollama Cloud | 2 | no | DeepSeek V4 Pro, Kimi K3 (writer) | weekly limits | `OLLAMA_API_KEY` |
| Z AI | 2 | no | GLM-4.7-Flash | 1 request at a time | `ZAI_API_KEY` |
| Cerebras | 2 | no | GLM-4.7 (checker) | 100 a day | `CEREBRAS_API_KEY` |
| SambaNova | 2 | no | DeepSeek V3.1 | 20 a day | `SAMBANOVA_API_KEY` |
| LLM7 | 3 | no | gpt-oss-20b | works without a key | `LLM7_API_KEY` (optional) |
| OVHcloud | 3 | no | gpt-oss-120b | 2/min anonymous | `OVH_API_KEY` (optional) |

To use a tier 2 or 3 provider: add its key as a GitHub secret, set `enabled: true` in `config/providers.yaml` (or switch
it on in Dashboard → Settings → AI writers).

**Left out on purpose:**
- Cohere: its free tier is non-commercial only.
- SiliconFlow and ModelScope: they require identity verification.
- xAI and DeepSeek: credit-based or trial only.
- Hugging Face: the free credit is too small.
- Cline and OpenCode: their free models are meant for their own tools.

**One account per provider.** Multiplying free quotas with extra accounts breaks the providers' terms.

**Privacy:** Gemini and Mistral free tiers may use prompts for training. The studio only sends public research and
scripts.

## Other services

| Service | Free allowance (config) | Notes |
|---|---|---|
| GitHub Actions | 2,000 min/month (private repo) | The planner keeps 200 in reserve; a self-hosted runner on your PC costs nothing extra |
| Supabase | 500 MB database, 1 GB storage | Previews expire 7 days after you decide; recipes kept forever |
| Cloudflare Pages + Workers | Free plan | Worker does light work only (10 ms CPU per request) |
| YouTube Data API | 10,000 units/day | Upload ≈1,600, thumbnail 50, search 100 |
| Kokoro TTS | Unlimited (runs in the job) | Apache-2.0, commercial use allowed |
| Pixabay / Pexels / Openverse | Free API keys (Pexels paused new keys Sept 2026); Openverse needs none | Licenses recorded per photo; Openverse limited to CC0/PDM |
| FRED, SEC EDGAR, Google News/Trends RSS, Hacker News, Reddit RSS, Wikipedia | Free | FRED needs a free key; SEC needs a contact user agent |
| Telegram Bot API | Free | |
| **X API** | **Pay-per-use, capped at $1.00/month** | ≈$0.015 per post at the time of writing; links blocked (≈$0.20 each). Check X's current minimum credit purchase before buying |
