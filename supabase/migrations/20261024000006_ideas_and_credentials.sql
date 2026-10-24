-- v2.3: AI Idea Generator, Idea Library, multi-credential AI API Manager.
-- The engine connects as the database owner (bypasses RLS). The dashboard can read everything except secrets
-- and may change only the columns listed in the GRANTs below. Credentials are added, replaced and deleted by the
-- Worker (service role), which encrypts keys server-side; the browser never receives a full key.

-- ---------------------------------------------------------------------------- AI credentials
create table public.ai_credentials (
  id uuid primary key default gen_random_uuid(),
  provider text not null references public.ai_providers(name) on delete cascade,
  label text not null check (length(label) between 1 and 80),
  owner_name text not null check (length(owner_name) between 1 and 80),
  authorized_use text not null check (length(authorized_use) between 3 and 300),
  authorized_at timestamptz not null default now(),
  key_hint text not null,                         -- e.g. "••••3f9a" — never the key itself
  enabled boolean not null default true,
  priority int not null default 100 check (priority between 1 and 1000),
  weight int not null default 1 check (weight between 0 and 100),
  -- Credentials share one rate/quota allowance unless the owner attests a separate account.
  quota_group text not null,
  separate_account_attested boolean not null default false,
  daily_request_cap int check (daily_request_cap is null or daily_request_cap >= 0),
  daily_token_cap bigint check (daily_token_cap is null or daily_token_cap >= 0),
  monthly_spend_cap_usd numeric(10,2) check (monthly_spend_cap_usd is null or monthly_spend_cap_usd >= 0),
  input_usd_per_mtok numeric(10,4) check (input_usd_per_mtok is null or input_usd_per_mtok >= 0),
  output_usd_per_mtok numeric(10,4) check (output_usd_per_mtok is null or output_usd_per_mtok >= 0),
  max_concurrency int not null default 2 check (max_concurrency between 1 and 16),
  health text not null default 'unknown' check (health in ('unknown','healthy','degraded','resting','invalid','exhausted')),
  consecutive_failures int not null default 0,
  circuit_open_until timestamptz,
  last_success_at timestamptz,
  last_error text,
  last_error_at timestamptz,
  last_tested_at timestamptz,
  last_test_result text,
  models jsonb not null default '[]'::jsonb,       -- models the provider listed for this key at the last test
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (provider, label),
  constraint quota_group_needs_attestation check (quota_group = provider or separate_account_attested)
);
create index ai_credentials_provider_idx on public.ai_credentials (provider, enabled, priority);
create trigger ai_credentials_touch before update on public.ai_credentials
  for each row execute function public.touch_updated_at();

-- Encrypted keys (AES-256-GCM, same format as oauth_secrets). Intentionally NO client policies.
create table public.ai_credential_secrets (
  credential_id uuid primary key references public.ai_credentials(id) on delete cascade,
  ciphertext text not null,
  key_version int not null default 1,
  updated_at timestamptz not null default now()
);

-- Per-provider routing settings.
alter table public.ai_providers
  add column key_strategy text not null default 'priority'
    check (key_strategy in ('round_robin','priority','least_utilized','health','weighted')),
  add column max_concurrency int not null default 2 check (max_concurrency between 1 and 32),
  add column request_timeout_s int not null default 120 check (request_timeout_s between 10 and 600),
  add column max_retries int not null default 2 check (max_retries between 0 and 5),
  add column use_env_key boolean not null default true;   -- the GitHub-secret key counts as one credential

-- Role assignments edited in the AI API Manager survive config syncs.
alter table public.ai_model_configs add column roles_custom boolean not null default false;

-- Which credential served each call, and whether cost is an estimate.
alter table public.provider_usage
  add column credential_id uuid references public.ai_credentials(id) on delete set null,
  add column cost_source text not null default 'none' check (cost_source in ('none','estimated','provider'));
create index provider_usage_credential_idx on public.provider_usage (credential_id, usage_date);

-- ---------------------------------------------------------------------------- Idea generator
create table public.idea_runs (
  id uuid primary key default gen_random_uuid(),
  trigger text not null default 'manual' check (trigger in ('manual','scheduled','regenerate')),
  status text not null default 'running' check (status in ('running','completed','partial','failed')),
  job_id uuid,
  config jsonb not null default '{}'::jsonb,
  requested_count int not null default 10 check (requested_count between 1 and 30),
  produced_count int not null default 0,
  evidence_count int not null default 0,
  sources_used jsonb not null default '{}'::jsonb,
  notes jsonb not null default '[]'::jsonb,       -- plain-language notes: provider substitutions, shortfalls
  error text,
  started_at timestamptz not null default now(),
  finished_at timestamptz,
  created_at timestamptz not null default now()
);
create index idea_runs_created_idx on public.idea_runs (created_at desc);

create table public.generated_ideas (
  id uuid primary key default gen_random_uuid(),
  run_id uuid not null references public.idea_runs(id) on delete cascade,
  rank int not null,
  title text not null,
  summary text not null,
  audience text not null,
  markets text[] not null default '{}',
  channel_slug text check (channel_slug in ('ai','money','both')),
  category text,
  trend_signals jsonb not null default '[]'::jsonb, -- [{source_id,title,url,publisher,adapter,published_at,retrieved_at}]
  trend_verified boolean not null default false,
  newest_evidence_at timestamptz,
  scores jsonb not null default '{}'::jsonb,       -- {trend, originality, international, feasibility, engagement} 0..1
  total numeric(5,1) not null check (total between 0 and 100),
  score_explanation text not null,
  assessment_notes jsonb not null default '{}'::jsonb,
  confidence text not null check (confidence in ('high','medium','low','unverified')),
  sensitivity text not null default 'none' check (sensitivity in ('none','sensitive','controversial','poorly_supported')),
  sensitivity_note text,
  suggested_format text,
  execution text,
  generated_by text,                               -- provider/model that proposed it
  assessed_by text,                                -- provider/model that assessed it
  fingerprint text not null,
  status text not null default 'new' check (status in ('new','saved','rejected','sent_to_studio','archived')),
  status_history jsonb not null default '[]'::jsonb,
  owner_note text check (owner_note is null or length(owner_note) <= 1000),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create index generated_ideas_run_idx on public.generated_ideas (run_id, rank);
create index generated_ideas_status_idx on public.generated_ideas (status, created_at desc);
create index generated_ideas_fingerprint_idx on public.generated_ideas (fingerprint);
create trigger generated_ideas_touch before update on public.generated_ideas
  for each row execute function public.touch_updated_at();

-- ---------------------------------------------------------------------------- RLS
alter table public.ai_credentials enable row level security;
alter table public.ai_credential_secrets enable row level security;
alter table public.idea_runs enable row level security;
alter table public.generated_ideas enable row level security;

create policy owner_select on public.ai_credentials for select to authenticated using ((select public.is_owner()));
create policy owner_update on public.ai_credentials for update to authenticated
  using ((select public.is_owner())) with check ((select public.is_owner()));
create policy owner_select on public.idea_runs for select to authenticated using ((select public.is_owner()));
create policy owner_select on public.generated_ideas for select to authenticated using ((select public.is_owner()));
create policy owner_update on public.generated_ideas for update to authenticated
  using ((select public.is_owner())) with check ((select public.is_owner()));

-- Column-level limits: the owner edits settings and statuses, never secrets, health or measured usage.
revoke insert, update, delete on public.ai_credentials from anon, authenticated;
grant update (label, owner_name, enabled, priority, weight, quota_group, separate_account_attested,
              daily_request_cap, daily_token_cap, monthly_spend_cap_usd, input_usd_per_mtok, output_usd_per_mtok,
              max_concurrency) on public.ai_credentials to authenticated;
revoke all on public.ai_credential_secrets from anon, authenticated;
revoke insert, update, delete on public.idea_runs from anon, authenticated;
revoke insert, update, delete on public.generated_ideas from anon, authenticated;
grant update (status, status_history, owner_note) on public.generated_ideas to authenticated;
revoke update on public.provider_usage from anon, authenticated;
revoke update on public.ai_model_configs from anon, authenticated;
grant update (enabled, priority, daily_request_limit, roles, roles_custom) on public.ai_model_configs to authenticated;
