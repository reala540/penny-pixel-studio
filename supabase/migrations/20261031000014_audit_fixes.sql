-- v3.3 audit fixes (26 Oct 2026). Independent of migration 13: safe to apply before or after it.
--
-- 1. Stop & clear could be run by ANY signed-in account: its guard tested current_user, which inside a
--    SECURITY DEFINER function is always the function's owner. Only the Worker (after its own owner check)
--    and the engine may run it now, and signed-in users can't call it directly at all.
-- 2. Approval is tied to the exact script version the owner reviewed; a changed version is refused.
--    Only packages that were really approved get an approval record.
-- 3. Changing the script of an approved package withdraws that approval (its posts wait for approval again);
--    a published package's script can't be replaced.
-- 4. Table privileges the API never uses (TRUNCATE, TRIGGER, REFERENCES) are removed from anon/authenticated.

create or replace function public.stop_and_clear()
returns jsonb
language plpgsql
security definer
set search_path = public
as $$
declare
  since timestamptz;
  active uuid[];
  fams uuid[];
  paths text[];
  n_jobs int; n_ideas int; n_gen int; n_runs int; n_sources int; n_notes int; n_projects int;
  v_claims jsonb := nullif(current_setting('request.jwt.claims', true), '')::jsonb;
  v_role text := coalesce(nullif(current_setting('request.jwt.claim.role', true), ''), v_claims->>'role', '');
begin
  -- current_user is this function's owner (postgres) inside SECURITY DEFINER, so it can't tell who called.
  -- Allowed: the Worker (service-role token) and the engine's direct database session (no token).
  if not (v_role = 'service_role' or (session_user = 'postgres' and v_claims is null)) then
    raise exception 'not authorised';
  end if;
  perform pg_advisory_xact_lock(hashtext('stop_and_clear'));
  -- what is running now (a job stuck as "running" for over a day is not live work and is left alone)
  select array_agg(id) into active from public.generation_jobs
   where status in ('queued', 'running', 'retrying') and coalesce(updated_at, created_at) > now() - interval '24 hours';
  if active is null then
    return jsonb_build_object('stopped', false, 'reason', 'nothing is running');
  end if;
  -- where this work began: the jobs themselves, and the idea (and idea run) a package job was making
  select min(created_at) into since from public.generation_jobs
   where id = any(active) or parent_job_id = any(active);
  select least(since, min(ci.created_at), min(r.created_at)) into since
    from public.generation_jobs j
    left join public.generated_ideas g on g.id::text = j.input->>'generated_idea_id'
    left join public.content_ideas ci on ci.id::text = j.input->>'content_idea_id' or ci.id = g.content_idea_id
    left join public.idea_runs r on r.id = g.run_id
   where j.id = any(active);

  insert into public.settings (key, value) values ('stop_requested_at', to_jsonb(now()))
  on conflict (key) do update set value = excluded.value;
  update public.generation_jobs set status = 'cancelled', finished_at = now(), progress = null,
         error_message = 'Stopped by the owner (Stop & clear)'
   where id = any(active);
  get diagnostics n_jobs = row_count;

  -- packages made since then (or by the stopped jobs), except any with published posts
  -- packages the stopped work made; one you already approved or scheduled is kept, and nothing published is touched
  select array_agg(p.id) into fams from public.content_projects p
   where p.parent_project_id is null
     and (p.id in (select project_id from public.generation_jobs where id = any(active) and project_id is not null)
          or (p.created_at >= since and p.status not in ('approved', 'scheduled', 'published')))
     and not exists (select 1 from public.published_posts pp join public.scheduled_posts sp on sp.id = pp.scheduled_post_id
                       join public.content_variants v on v.id = sp.variant_id
                       join public.content_projects f on f.id = v.project_id
                      where f.id = p.id or f.parent_project_id = p.id);
  n_projects := coalesce(array_length(fams, 1), 0);
  paths := public.erase_projects(coalesce(fams, '{}'));

  delete from public.generation_jobs where id = any(active)
     or (created_at >= since and (project_id is null or not exists (select 1 from public.content_projects p where p.id = project_id)));
  delete from public.generated_ideas where created_at >= since;
  get diagnostics n_gen = row_count;
  delete from public.idea_runs r where r.created_at >= since
     and not exists (select 1 from public.generated_ideas g where g.run_id = r.id);
  get diagnostics n_runs = row_count;
  delete from public.content_ideas ci where ci.created_at >= since
     and not exists (select 1 from public.content_projects p where p.idea_id = ci.id);
  get diagnostics n_ideas = row_count;
  -- sources found since then that no remaining idea or claim uses
  delete from public.research_sources s where s.retrieved_at >= since
     and not exists (select 1 from public.content_ideas ci where s.id = any(ci.source_ids))
     and not exists (select 1 from public.research_claims c where c.source_id = s.id);
  get diagnostics n_sources = row_count;
  delete from public.notifications where created_at >= since;
  get diagnostics n_notes = row_count;

  insert into public.audit_logs (actor, action, target_type, details)
  values (public.audit_actor(), 'stop_and_clear', 'studio',
          jsonb_build_object('since', since, 'jobs_stopped', n_jobs, 'packages', n_projects, 'ideas', n_ideas + n_gen,
                             'idea_runs', n_runs, 'sources', n_sources, 'notifications', n_notes,
                             'files', coalesce(array_length(paths, 1), 0)));
  return jsonb_build_object('stopped', true, 'since', since, 'jobs_stopped', n_jobs, 'packages', n_projects,
                            'ideas', n_ideas + n_gen, 'sources', n_sources, 'notifications', n_notes,
                            'storage_paths', to_jsonb(paths));
end;
$$;

revoke all on function public.stop_and_clear() from public, anon, authenticated;
grant execute on function public.stop_and_clear() to service_role;

-- 2. version-exact approval ------------------------------------------------------------------
drop function if exists public.approve_project(uuid, text);
create function public.approve_project(p_project_id uuid, p_notes text default null,
                                       p_expected_version uuid default null)
returns integer
language plpgsql
security definer
set search_path = public
as $$
declare
  v_count int := 0;
  v_variant record;
  v_head record;
  v_ids uuid[];
begin
  if not public.is_owner() then
    raise exception 'owner only';
  end if;
  select * into v_head from public.content_projects where id = p_project_id for update;
  if not found then
    raise exception 'This package no longer exists.';
  end if;
  if v_head.status not in ('ready_for_review', 'needs_attention') then
    raise exception 'This package is no longer waiting for approval (it is %). Reload to see its current state.', v_head.status;
  end if;
  if p_expected_version is null or v_head.current_script_version_id is distinct from p_expected_version then
    raise exception 'The script changed after you opened it. Reload and review the current version before approving.';
  end if;
  select array_agg(id) into v_ids from public.content_projects
   where (id = p_project_id or parent_project_id = p_project_id) and status in ('ready_for_review', 'needs_attention');
  perform 1 from public.content_projects where id = any(v_ids) for update;
  insert into public.approvals (target_type, target_id, decision, script_version_id, notes, decided_by)
  select 'project', p.id, 'approved', p.current_script_version_id, p_notes, auth.uid()
    from public.content_projects p where p.id = any(v_ids);
  update public.content_projects set status = 'approved', approved_script_version_id = current_script_version_id
   where id = any(v_ids);
  for v_variant in
    select v.id from public.content_variants v
     where v.project_id = any(v_ids) and v.status in ('ready_for_review', 'needs_attention')
  loop
    insert into public.approvals (target_type, target_id, decision, decided_by)
    values ('variant', v_variant.id, 'approved', auth.uid());
    update public.content_variants set status = 'approved' where id = v_variant.id;
    v_count := v_count + 1;
  end loop;
  return v_count;
end;
$$;
revoke all on function public.approve_project(uuid, text, uuid) from public, anon;
grant execute on function public.approve_project(uuid, text, uuid) to authenticated;

-- 3. a new script version withdraws the approval of the old one --------------------------------
create or replace function public.withdraw_approval_on_new_script()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
begin
  if new.current_script_version_id is distinct from old.current_script_version_id then
    if old.status = 'published' then
      raise exception 'This package is already published; its script can''t be replaced.';
    end if;
    if old.approved_script_version_id is not null then
      new.approved_script_version_id := null;
      -- its posts go back to waiting for approval (sync_variant_schedule moves scheduled -> pending_approval)
      update public.content_variants set status = 'ready_for_review'
       where project_id = new.id and status = 'approved';
      insert into public.audit_logs (actor, action, target_type, target_id, details)
      values (public.audit_actor(), 'approval_withdrawn', 'content_project', new.id::text,
              jsonb_build_object('reason', 'script changed after approval',
                                 'approved_version', old.approved_script_version_id,
                                 'new_version', new.current_script_version_id));
    end if;
  end if;
  return new;
end;
$$;
revoke all on function public.withdraw_approval_on_new_script() from public, anon, authenticated;
drop trigger if exists content_projects_withdraw_approval on public.content_projects;
create trigger content_projects_withdraw_approval before update of current_script_version_id on public.content_projects
  for each row execute function public.withdraw_approval_on_new_script();

-- 3b. a published post's text is the record of what went out: it can't be edited afterwards
create or replace function public.keep_published_variant_text()
returns trigger
language plpgsql
set search_path = public
as $$
begin
  if old.status = 'published' and (new.body is distinct from old.body or new.title is distinct from old.title) then
    raise exception 'This post is already published; its text can''t be changed.';
  end if;
  return new;
end;
$$;
revoke all on function public.keep_published_variant_text() from public, anon, authenticated;
drop trigger if exists content_variants_keep_published_text on public.content_variants;
create trigger content_variants_keep_published_text before update of body, title on public.content_variants
  for each row execute function public.keep_published_variant_text();

-- 3c. scheduling rules hold on every path the owner can use (the API too, not only the reschedule function)
create or replace function public.owner_schedule_rules()
returns trigger
language plpgsql
set search_path = public
as $$
begin
  -- only signed-in callers; the engine and Worker plan slots themselves
  if auth.uid() is null or new.scheduled_at is not distinct from old.scheduled_at then
    return new;
  end if;
  if old.status not in ('scheduled', 'pending_approval') then
    raise exception 'This post can no longer be moved';
  end if;
  if new.scheduled_at <= now() then
    raise exception 'Choose a future time';
  end if;
  -- the reschedule and schedule functions check clashes themselves (a bulk move passes through brief overlaps);
  -- a direct change to the table is checked here
  if coalesce(current_setting('request.path', true), '') like '/rpc/%' then
    return new;
  end if;
  if exists (select 1 from public.scheduled_posts
              where social_account_id = new.social_account_id and id <> new.id
                and status not in ('cancelled', 'failed')
                and abs(extract(epoch from scheduled_at - new.scheduled_at)) < 1800) then
    raise exception 'Another post on this account is within 30 minutes. Choose a different time.';
  end if;
  return new;
end;
$$;
revoke all on function public.owner_schedule_rules() from public, anon, authenticated;
drop trigger if exists scheduled_posts_owner_rules on public.scheduled_posts;
create trigger scheduled_posts_owner_rules before update of scheduled_at on public.scheduled_posts
  for each row execute function public.owner_schedule_rules();

-- 4. least privilege on tables ------------------------------------------------------------------
do $$
declare t record;
begin
  for t in select c.relname from pg_class c join pg_namespace n on n.oid = c.relnamespace
            where n.nspname = 'public' and c.relkind in ('r', 'p') loop
    execute format('revoke truncate, trigger, references on public.%I from anon, authenticated', t.relname);
  end loop;
end $$;
alter default privileges in schema public revoke truncate, trigger, references on tables from anon, authenticated;
