-- AI Content Studio v2.1 — Row Level Security, function privileges, storage.
-- The engine (GitHub Actions) connects with the database owner role and bypasses RLS.
-- The dashboard uses the public anon key + the owner's session, so RLS is the gate.

-- Enable RLS on every public table.
do $$
declare t record;
begin
  for t in select tablename from pg_tables where schemaname = 'public'
  loop
    execute format('alter table public.%I enable row level security', t.tablename);
  end loop;
end;
$$;

-- Owner can read everything except secrets.
do $$
declare t record;
begin
  for t in select tablename from pg_tables
            where schemaname = 'public'
              and tablename not in ('oauth_secrets','app_owner')
  loop
    execute format('create policy owner_select on public.%I for select to authenticated using (public.is_owner())', t.tablename);
  end loop;
end;
$$;

create policy owner_select_self on public.app_owner
  for select to authenticated using (user_id = auth.uid());

-- oauth_secrets: intentionally NO policies. Only the service role / engine can touch it.

-- Owner write permissions, limited to what the dashboard actually needs.
create policy owner_update on public.settings for update to authenticated using (public.is_owner()) with check (public.is_owner());
create policy owner_insert on public.settings for insert to authenticated with check (public.is_owner());

create policy owner_update on public.brands for update to authenticated using (public.is_owner()) with check (public.is_owner());
create policy owner_update on public.channel_profiles for update to authenticated using (public.is_owner()) with check (public.is_owner());
create policy owner_update on public.social_accounts for update to authenticated using (public.is_owner()) with check (public.is_owner());

create policy owner_update on public.content_ideas for update to authenticated using (public.is_owner()) with check (public.is_owner());
create policy owner_update on public.content_projects for update to authenticated using (public.is_owner()) with check (public.is_owner());
create policy owner_update on public.content_variants for update to authenticated using (public.is_owner()) with check (public.is_owner());
create policy owner_update on public.thumbnails for update to authenticated using (public.is_owner()) with check (public.is_owner());
create policy owner_update on public.research_claims for update to authenticated using (public.is_owner()) with check (public.is_owner());

-- Owner edits create new script versions (immutable rows) and approvals.
create policy owner_insert on public.script_versions for insert to authenticated with check (public.is_owner() and origin = 'owner_edit');
create policy owner_insert on public.approvals for insert to authenticated with check (public.is_owner() and decided_by = auth.uid());

-- Owner can reschedule/cancel posts but cannot mark them published.
create policy owner_update on public.scheduled_posts for update to authenticated
  using (public.is_owner())
  with check (public.is_owner() and status in ('pending_approval','scheduled','cancelled'));

-- Owner can request jobs (regenerate, run batch) — the engine does the work.
create policy owner_insert on public.generation_jobs for insert to authenticated
  with check (public.is_owner() and requested_by = 'owner' and status = 'queued');
create policy owner_update on public.generation_jobs for update to authenticated
  using (public.is_owner()) with check (public.is_owner() and status in ('cancelled','queued'));

create policy owner_update on public.manual_tasks for update to authenticated using (public.is_owner()) with check (public.is_owner());
create policy owner_update on public.ai_providers for update to authenticated using (public.is_owner()) with check (public.is_owner());
create policy owner_update on public.ai_model_configs for update to authenticated using (public.is_owner()) with check (public.is_owner());
create policy owner_update on public.budgets for update to authenticated using (public.is_owner()) with check (public.is_owner() and monthly_cap_usd <= 1.00);
create policy owner_update on public.automation_rules for update to authenticated using (public.is_owner()) with check (public.is_owner());
create policy owner_insert on public.audit_logs for insert to authenticated with check (public.is_owner() and actor = 'owner');

-- Function privileges: Supabase exposes public functions over RPC, so lock them down.
revoke all on function public.reserve_budget(text, numeric, text) from public, anon, authenticated;
revoke all on function public.claim_ownership() from public, anon;
grant execute on function public.claim_ownership() to authenticated;
revoke all on function public.is_owner() from public, anon;
grant execute on function public.is_owner() to authenticated;
revoke all on function public.forbid_update() from public, anon, authenticated;
revoke all on function public.touch_updated_at() from public, anon, authenticated;

-- Private storage bucket for previews, thumbnails, narration and recipes.
insert into storage.buckets (id, name, public)
values ('studio', 'studio', false)
on conflict (id) do nothing;

create policy studio_owner_read on storage.objects
  for select to authenticated
  using (bucket_id = 'studio' and public.is_owner());
revoke all on function public.sync_variant_schedule() from public, anon, authenticated;
