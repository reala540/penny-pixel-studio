-- v3.0: one-button Stop & clear, and automatic replacement of packages left waiting for the owner.

-- ---------------------------------------------------------------------------------------------------------------
-- 1. Erase packages (and everything made for them). A package with anything published is never erased:
--    published posts are permanent. Returns the storage paths of the files to remove.

create or replace function public.erase_projects(p_ids uuid[])
returns text[]
language plpgsql
security definer
set search_path = public
as $$
declare
  fam uuid[];
  paths text[];
begin
  select array_agg(id) into fam from public.content_projects where id = any(p_ids) or parent_project_id = any(p_ids);
  if fam is null then
    return '{}';
  end if;
  if exists (select 1 from public.published_posts pp
               join public.scheduled_posts sp on sp.id = pp.scheduled_post_id
               join public.content_variants v on v.id = sp.variant_id
              where v.project_id = any(fam)) then
    raise exception 'a package with published posts can''t be erased';
  end if;
  select coalesce(array_agg(storage_path) filter (where storage_path is not null), '{}') into paths
    from public.media_assets where project_id = any(fam);
  delete from public.approvals where target_id = any(fam)
     or target_id in (select id from public.content_variants where project_id = any(fam))
     or target_id in (select id from public.thumbnails where project_id = any(fam));
  update public.content_projects set current_script_version_id = null, approved_script_version_id = null
   where id = any(fam);
  delete from public.content_projects where id = any(fam) and parent_project_id is not null;
  delete from public.content_projects where id = any(fam);  -- cascades: scripts, scenes, claims, media, variants, posts, jobs
  return paths;
end;
$$;
revoke all on function public.erase_projects(uuid[]) from public, anon, authenticated;

-- ---------------------------------------------------------------------------------------------------------------
-- 2. Stop & clear: stop everything running and erase what it made, from the ideas it started from up to now.
--    Called by the Worker (which also cancels the GitHub runs and removes the files). The engine sees
--    `stop_requested_at` and stops at its next step.

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
begin
  if not (public.is_owner() or current_user in ('service_role', 'postgres')) then
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
revoke all on function public.stop_and_clear() from public, anon;
grant execute on function public.stop_and_clear() to authenticated, service_role;

-- ---------------------------------------------------------------------------------------------------------------
-- 3. Automatic replacement of packages held for the owner (Smart Mode): remind, then replace with a safer idea.
insert into public.settings (key, value)
values ('auto_replace', '{"enabled": true, "remind_after_hours": 12, "replace_after_hours": 24, "max_per_week": 2}')
on conflict (key) do nothing;

create table public.auto_replacements (
  id bigint generated always as identity primary key,
  channel_slug text not null check (channel_slug in ('ai', 'money')),
  old_title text not null,
  reasons text[] not null default '{}',
  new_project_id uuid references public.content_projects(id) on delete set null,
  new_title text,
  outcome text not null check (outcome in ('replaced', 'erased_no_safe_idea', 'failed')),
  detail text,
  created_at timestamptz not null default now()
);
create index auto_replacements_week_idx on public.auto_replacements (channel_slug, created_at desc);
alter table public.auto_replacements enable row level security;
create policy owner_read on public.auto_replacements for select to authenticated using (public.is_owner());
