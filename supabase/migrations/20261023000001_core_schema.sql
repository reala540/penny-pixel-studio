-- AI Content Studio v2.1 — core schema
-- All timestamps are UTC (timestamptz). Display timezone lives in settings.

create extension if not exists pgcrypto;

-- ---------------------------------------------------------------------------
-- Ownership: exactly one owner account controls the studio.
-- ---------------------------------------------------------------------------
create table public.app_owner (
  singleton boolean primary key default true check (singleton),
  user_id uuid not null unique,
  email text not null,
  claimed_at timestamptz not null default now()
);

create or replace function public.is_owner()
returns boolean
language sql
stable
security definer
set search_path = public
as $$
  select exists (select 1 from public.app_owner where user_id = auth.uid());
$$;

-- The first signed-in user may claim ownership once. After that, nobody else can.
create or replace function public.claim_ownership()
returns boolean
language plpgsql
security definer
set search_path = public
as $$
declare
  v_email text;
begin
  if auth.uid() is null then
    raise exception 'not signed in';
  end if;
  if exists (select 1 from public.app_owner) then
    return public.is_owner();
  end if;
  select coalesce(auth.jwt() ->> 'email', '') into v_email;
  insert into public.app_owner (user_id, email) values (auth.uid(), v_email);
  return true;
end;
$$;

-- ---------------------------------------------------------------------------
-- Settings (key/value, JSON values)
-- ---------------------------------------------------------------------------
create table public.settings (
  key text primary key,
  value jsonb not null,
  updated_at timestamptz not null default now()
);

-- ---------------------------------------------------------------------------
-- Brand, channels and social accounts
-- ---------------------------------------------------------------------------
create table public.brands (
  id uuid primary key default gen_random_uuid(),
  name text not null,
  tagline text,
  palette jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create table public.channel_profiles (
  id uuid primary key default gen_random_uuid(),
  brand_id uuid not null references public.brands(id) on delete cascade,
  slug text not null unique,                 -- 'ai' | 'money'
  display_name text not null,
  host_persona text not null,
  topic_focus text not null,
  voice_profile jsonb not null default '{}'::jsonb,   -- tone, style rules, banned phrases, tts voice
  audience_profile jsonb not null default '{}'::jsonb,
  design jsonb not null default '{}'::jsonb,          -- colors, fonts, thumbnail identity
  disclaimer text,
  created_at timestamptz not null default now()
);

create table public.social_accounts (
  id uuid primary key default gen_random_uuid(),
  platform text not null check (platform in ('youtube','facebook','tiktok','x')),
  label text not null,
  channel_profile_id uuid references public.channel_profiles(id) on delete set null,
  topic_mix jsonb not null default '{"ai":0.5,"money":0.5}'::jsonb,
  weekly_targets jsonb not null default '{}'::jsonb,
  external_id text,                 -- channel id / page id / user id once connected
  handle text,
  enabled boolean not null default true,
  created_at timestamptz not null default now(),
  unique (platform, label)
);

-- Connection metadata is visible to the owner. Encrypted tokens live in oauth_secrets,
-- which has no client-readable policy at all.
create table public.oauth_connections (
  id uuid primary key default gen_random_uuid(),
  social_account_id uuid not null unique references public.social_accounts(id) on delete cascade,
  status text not null default 'disconnected'
    check (status in ('disconnected','connected','expired','error','needs_reauth')),
  scopes text[] not null default '{}',
  app_publish_mode text not null default 'unverified'
    check (app_publish_mode in ('unverified','testing','production','audited')),
  last_checked_at timestamptz,
  last_error text,
  token_expires_at timestamptz,
  connected_at timestamptz,
  updated_at timestamptz not null default now()
);

create table public.oauth_secrets (
  social_account_id uuid primary key references public.social_accounts(id) on delete cascade,
  ciphertext text not null,          -- AES-256-GCM, base64(iv || ciphertext+tag)
  key_version int not null default 1,
  updated_at timestamptz not null default now()
);

-- ---------------------------------------------------------------------------
-- Research
-- ---------------------------------------------------------------------------
create table public.research_sources (
  id uuid primary key default gen_random_uuid(),
  adapter text not null,
  title text not null,
  publisher text,
  url text not null,
  published_at timestamptz,
  event_date date,
  retrieved_at timestamptz not null default now(),
  summary text,
  body_excerpt text,                  -- adapter metrics (JSON text)
  body_text text,                     -- best-effort article text used for claim checking
  credibility text not null default 'unrated'
    check (credibility in ('official','primary_data','reputable_media','community','unrated')),
  topic text check (topic in ('ai','money','both')),
  fresh_until timestamptz,
  verification_status text not null default 'unverified'
    check (verification_status in ('unverified','verified','disputed','stale')),
  content_hash text not null unique
);
create index research_sources_topic_idx on public.research_sources (topic, retrieved_at desc);

create table public.content_ideas (
  id uuid primary key default gen_random_uuid(),
  channel_slug text not null check (channel_slug in ('ai','money')),
  title text not null,
  angle text,
  status text not null default 'proposed'
    check (status in ('proposed','shortlisted','selected','produced','rejected','expired','saved')),
  score numeric(5,2) not null default 0,
  score_breakdown jsonb not null default '{}'::jsonb,
  explanation text,
  is_experiment boolean not null default false,
  source_ids uuid[] not null default '{}',
  batch_week date,
  created_at timestamptz not null default now()
);
create index content_ideas_week_idx on public.content_ideas (batch_week, channel_slug, score desc);

-- ---------------------------------------------------------------------------
-- Content projects, scripts, scenes, claims
-- ---------------------------------------------------------------------------
create table public.content_projects (
  id uuid primary key default gen_random_uuid(),
  channel_slug text not null check (channel_slug in ('ai','money')),
  idea_id uuid references public.content_ideas(id) on delete set null,
  format text not null check (format in ('long','short')),
  parent_project_id uuid references public.content_projects(id) on delete cascade,
  title text not null,
  status text not null default 'draft'
    check (status in ('draft','scripting','verifying','rendering','ready_for_review',
                      'needs_attention','approved','scheduled','published','rejected','failed','archived')),
  batch_week date,
  current_script_version_id uuid,
  approved_script_version_id uuid,
  quality_report jsonb not null default '{}'::jsonb,
  recipe jsonb not null default '{}'::jsonb,           -- everything needed to re-render
  fresh_until timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create index content_projects_week_idx on public.content_projects (batch_week, status);

create table public.script_versions (
  id uuid primary key default gen_random_uuid(),
  project_id uuid not null references public.content_projects(id) on delete cascade,
  version int not null,
  origin text not null check (origin in ('ai','owner_edit','rewrite')),
  hook text,
  body jsonb not null,               -- validated Script object
  word_count int not null default 0,
  provider_trail jsonb not null default '[]'::jsonb,
  created_at timestamptz not null default now(),
  unique (project_id, version)
);
-- Script versions are immutable: edits create a new version.
create or replace function public.forbid_update()
returns trigger language plpgsql set search_path = public as $$
begin
  raise exception '% rows are immutable; insert a new version instead', tg_table_name;
end;
$$;
create trigger script_versions_immutable before update on public.script_versions
  for each row execute function public.forbid_update();

alter table public.content_projects
  add constraint content_projects_current_script_fk
    foreign key (current_script_version_id) references public.script_versions(id) on delete set null,
  add constraint content_projects_approved_script_fk
    foreign key (approved_script_version_id) references public.script_versions(id) on delete set null;

create table public.scenes (
  id uuid primary key default gen_random_uuid(),
  script_version_id uuid not null references public.script_versions(id) on delete cascade,
  position int not null,
  narration text not null,
  est_seconds numeric(6,2) not null default 0,
  visual jsonb not null default '{}'::jsonb,
  on_screen_text text,
  claim_ids text[] not null default '{}',
  render_hash text,
  unique (script_version_id, position)
);

create table public.research_claims (
  id uuid primary key default gen_random_uuid(),
  project_id uuid not null references public.content_projects(id) on delete cascade,
  script_version_id uuid references public.script_versions(id) on delete cascade,
  claim_key text not null,
  claim_text text not null,
  source_id uuid references public.research_sources(id) on delete set null,
  source_published_at timestamptz,
  data_period text,
  retrieved_at timestamptz,
  confidence numeric(3,2) not null default 0,
  status text not null default 'unverified'
    check (status in ('unverified','supported','partially_supported','unsupported','contradicted','opinion','stale')),
  checker_notes text,
  reviewer_notes text,
  created_at timestamptz not null default now()
);
create index research_claims_project_idx on public.research_claims (project_id, status);

-- ---------------------------------------------------------------------------
-- Media, licensing, variants, thumbnails
-- ---------------------------------------------------------------------------
create table public.license_records (
  id uuid primary key default gen_random_uuid(),
  source_url text not null,
  provider text not null,              -- pexels, pixabay, wikimedia, original, youtube_audio_library ...
  creator text,
  license text not null,
  attribution_required boolean not null default false,
  attribution_text text,
  allowed_usage text not null default 'commercial',
  downloaded_at timestamptz not null default now(),
  unique (source_url)
);

create table public.media_assets (
  id uuid primary key default gen_random_uuid(),
  project_id uuid references public.content_projects(id) on delete cascade,
  kind text not null check (kind in ('narration','music','image','video_clip','chart','caption',
                                     'preview_video','final_video','thumbnail','recipe')),
  storage_path text,                   -- Supabase Storage path (bucket 'studio')
  local_hint text,
  bytes bigint,
  duration_seconds numeric(8,2),
  content_hash text,
  license_record_id uuid references public.license_records(id) on delete set null,
  expires_at timestamptz,
  deleted_at timestamptz,
  created_at timestamptz not null default now()
);
create index media_assets_expiry_idx on public.media_assets (expires_at) where deleted_at is null;

create table public.content_variants (
  id uuid primary key default gen_random_uuid(),
  project_id uuid not null references public.content_projects(id) on delete cascade,
  social_account_id uuid not null references public.social_accounts(id) on delete cascade,
  kind text not null check (kind in ('long_video','short_video','reel','text_post','image_post')),
  title text,
  body text,                           -- caption / description / post text
  tags text[] not null default '{}',
  hashtags text[] not null default '{}',
  preview_asset_id uuid references public.media_assets(id) on delete set null,
  status text not null default 'ready_for_review'
    check (status in ('draft','ready_for_review','needs_attention','approved','rejected','skipped','published')),
  checks jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table public.thumbnails (
  id uuid primary key default gen_random_uuid(),
  project_id uuid not null references public.content_projects(id) on delete cascade,
  variant_label text not null,
  headline text not null,
  template text not null,
  options jsonb not null default '{}'::jsonb,
  asset_id uuid references public.media_assets(id) on delete set null,
  selected boolean not null default false,
  created_at timestamptz not null default now()
);

-- ---------------------------------------------------------------------------
-- Jobs (persistent source of truth for every pipeline stage)
-- ---------------------------------------------------------------------------
create table public.generation_jobs (
  id uuid primary key default gen_random_uuid(),
  job_type text not null,              -- research, score, script, verify, render_preview, render_final, publish, ...
  project_id uuid references public.content_projects(id) on delete cascade,
  parent_job_id uuid references public.generation_jobs(id) on delete set null,
  idempotency_key text not null unique,
  status text not null default 'pending'
    check (status in ('pending','queued','running','completed','needs_review','blocked',
                      'retrying','failed','cancelled','expired')),
  input jsonb not null default '{}'::jsonb,
  output jsonb not null default '{}'::jsonb,
  attempts int not null default 0,
  max_attempts int not null default 3,
  next_attempt_at timestamptz,
  error_kind text check (error_kind in ('transient','permanent','auth','quota','validation','unknown')),
  error_message text,
  provider_usage jsonb not null default '[]'::jsonb,
  requested_by text not null default 'system',
  started_at timestamptz,
  finished_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create index generation_jobs_status_idx on public.generation_jobs (status, next_attempt_at);
create index generation_jobs_project_idx on public.generation_jobs (project_id, created_at desc);

create table public.job_attempts (
  id uuid primary key default gen_random_uuid(),
  job_id uuid not null references public.generation_jobs(id) on delete cascade,
  attempt int not null,
  status text not null,
  error_kind text,
  error_message text,
  log_excerpt text,
  started_at timestamptz not null default now(),
  finished_at timestamptz
);

-- ---------------------------------------------------------------------------
-- Approval, scheduling and publishing
-- ---------------------------------------------------------------------------
create table public.approvals (
  id uuid primary key default gen_random_uuid(),
  target_type text not null check (target_type in ('project','variant','thumbnail','reply')),
  target_id uuid not null,
  decision text not null check (decision in ('approved','rejected','changes_requested','skipped')),
  script_version_id uuid references public.script_versions(id) on delete set null,
  notes text,
  decided_by uuid,
  decided_at timestamptz not null default now()
);
create index approvals_target_idx on public.approvals (target_type, target_id, decided_at desc);

create table public.scheduled_posts (
  id uuid primary key default gen_random_uuid(),
  variant_id uuid not null references public.content_variants(id) on delete cascade,
  social_account_id uuid not null references public.social_accounts(id) on delete cascade,
  scheduled_at timestamptz not null,
  status text not null default 'pending_approval'
    check (status in ('pending_approval','scheduled','publishing','published','failed',
                      'needs_manual','needs_review','cancelled','blocked')),
  idempotency_key text not null unique,
  attempts int not null default 0,
  last_error text,
  locked_until timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create index scheduled_posts_due_idx on public.scheduled_posts (status, scheduled_at);

create table public.published_posts (
  id uuid primary key default gen_random_uuid(),
  scheduled_post_id uuid not null unique references public.scheduled_posts(id) on delete cascade,
  platform text not null,
  platform_post_id text,
  url text,
  visibility text,
  method text not null check (method in ('api','api_draft','manual')),
  verified_at timestamptz,
  published_at timestamptz not null default now()
);

create table public.manual_tasks (
  id uuid primary key default gen_random_uuid(),
  scheduled_post_id uuid references public.scheduled_posts(id) on delete cascade,
  platform text not null,
  title text not null,
  instructions text not null,
  deep_link text,
  status text not null default 'open' check (status in ('open','done','dismissed')),
  created_at timestamptz not null default now(),
  done_at timestamptz
);

-- ---------------------------------------------------------------------------
-- Analytics & engagement (MVP stores what is available; UI comes later)
-- ---------------------------------------------------------------------------
create table public.platform_metrics (
  id uuid primary key default gen_random_uuid(),
  published_post_id uuid not null references public.published_posts(id) on delete cascade,
  captured_at timestamptz not null default now(),
  metrics jsonb not null
);

create table public.comments (
  id uuid primary key default gen_random_uuid(),
  platform text not null,
  published_post_id uuid references public.published_posts(id) on delete cascade,
  external_id text not null,
  author text,
  body text not null,
  classification text,
  deep_link text,
  created_at timestamptz not null default now(),
  unique (platform, external_id)
);

create table public.reply_drafts (
  id uuid primary key default gen_random_uuid(),
  comment_id uuid not null references public.comments(id) on delete cascade,
  body text not null,
  needs_owner boolean not null default true,
  status text not null default 'draft' check (status in ('draft','approved','sent','discarded')),
  created_at timestamptz not null default now()
);

-- ---------------------------------------------------------------------------
-- AI providers, usage, budgets
-- ---------------------------------------------------------------------------
create table public.ai_providers (
  name text primary key,
  enabled boolean not null default true,
  commercial_use_ok boolean not null default false,
  base_url text not null,
  key_env text,
  notes text,
  circuit_open_until timestamptz,
  last_success_at timestamptz,
  last_error text,
  updated_at timestamptz not null default now()
);

create table public.ai_model_configs (
  id uuid primary key default gen_random_uuid(),
  provider text not null references public.ai_providers(name) on delete cascade,
  model text not null,
  roles text[] not null default '{}',
  context_tokens int,
  daily_request_limit int,
  daily_token_limit int,
  supports_json boolean not null default true,
  priority int not null default 100,
  enabled boolean not null default true,
  unique (provider, model)
);

create table public.provider_usage (
  id bigint generated always as identity primary key,
  provider text not null,
  model text,
  service text not null default 'llm',     -- llm, x_api, youtube_api, tiktok_api, github_minutes, storage
  role text,
  job_id uuid,
  usage_date date not null default (now() at time zone 'utc')::date,
  requests int not null default 1,
  input_tokens int not null default 0,
  output_tokens int not null default 0,
  units int not null default 0,            -- e.g. YouTube quota units, GitHub minutes
  cost_usd numeric(10,4) not null default 0,
  success boolean not null default true,
  latency_ms int,
  error text,
  created_at timestamptz not null default now()
);
create index provider_usage_day_idx on public.provider_usage (provider, usage_date);

create table public.budgets (
  service text primary key,              -- e.g. 'x_api'
  monthly_cap_usd numeric(10,4) not null,
  hard_stop boolean not null default true,
  enabled boolean not null default true,
  notes text,
  updated_at timestamptz not null default now()
);

create table public.budget_reservations (
  id uuid primary key default gen_random_uuid(),
  service text not null references public.budgets(service),
  month date not null,                   -- first day of month (UTC)
  amount_usd numeric(10,4) not null,
  status text not null default 'reserved' check (status in ('reserved','committed','released')),
  reference text not null unique,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

-- Atomically reserve spend, refusing anything that would exceed the monthly cap.
create or replace function public.reserve_budget(p_service text, p_amount numeric, p_reference text)
returns boolean
language plpgsql
set search_path = public
as $$
declare
  v_cap numeric;
  v_enabled boolean;
  v_month date := date_trunc('month', now() at time zone 'utc')::date;
  v_used numeric;
begin
  select monthly_cap_usd, enabled into v_cap, v_enabled
    from public.budgets where service = p_service for update;
  if v_cap is null or not v_enabled then
    return false;
  end if;
  if exists (select 1 from public.budget_reservations where reference = p_reference and status <> 'released') then
    return true;  -- idempotent
  end if;
  select coalesce(sum(amount_usd), 0) into v_used
    from public.budget_reservations
   where service = p_service and month = v_month and status in ('reserved','committed');
  if v_used + p_amount > v_cap then
    return false;
  end if;
  insert into public.budget_reservations (service, month, amount_usd, reference)
  values (p_service, v_month, p_amount, p_reference)
  on conflict (reference) do update set status = 'reserved', amount_usd = excluded.amount_usd, updated_at = now();
  return true;
end;
$$;

-- ---------------------------------------------------------------------------
-- Automation, notifications, audit
-- ---------------------------------------------------------------------------
create table public.automation_rules (
  id uuid primary key default gen_random_uuid(),
  name text not null unique,
  enabled boolean not null default true,
  config jsonb not null default '{}'::jsonb,
  updated_at timestamptz not null default now()
);

create table public.notifications (
  id uuid primary key default gen_random_uuid(),
  channel text not null default 'telegram',
  kind text not null,
  title text not null,
  body text,
  link text,
  dedupe_key text unique,
  sent_at timestamptz,
  error text,
  created_at timestamptz not null default now()
);

create table public.audit_logs (
  id bigint generated always as identity primary key,
  actor text not null,                   -- 'owner', 'engine', 'worker', 'telegram'
  action text not null,
  target_type text,
  target_id text,
  details jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);
create index audit_logs_created_idx on public.audit_logs (created_at desc);

-- keep updated_at fresh
create or replace function public.touch_updated_at()
returns trigger language plpgsql set search_path = public as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

do $$
declare t text;
begin
  foreach t in array array['content_projects','content_variants','generation_jobs','scheduled_posts',
                           'oauth_connections','ai_providers','budgets','budget_reservations',
                           'automation_rules','settings']
  loop
    execute format('create trigger %I_touch before update on public.%I for each row execute function public.touch_updated_at()', t, t);
  end loop;
end;
$$;

-- Approving or rejecting a variant moves its scheduled posts. Publishing re-checks approval anyway.
create or replace function public.sync_variant_schedule()
returns trigger language plpgsql set search_path = public as $$
begin
  if new.status is distinct from old.status then
    if new.status = 'approved' then
      update public.scheduled_posts set status = 'scheduled'
       where variant_id = new.id and status = 'pending_approval';
    elsif new.status in ('rejected', 'skipped') then
      update public.scheduled_posts set status = 'cancelled'
       where variant_id = new.id and status in ('pending_approval', 'scheduled');
    elsif new.status in ('ready_for_review', 'needs_attention', 'draft') then
      update public.scheduled_posts set status = 'pending_approval'
       where variant_id = new.id and status = 'scheduled';
    end if;
  end if;
  return new;
end;
$$;
create trigger content_variants_schedule after update of status on public.content_variants
  for each row execute function public.sync_variant_schedule();
