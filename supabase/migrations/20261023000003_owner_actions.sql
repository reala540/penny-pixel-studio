-- Owner actions that need to touch rows the owner cannot write directly.

-- Mark a manual task done. If it belongs to a post, record that post as published manually.
create or replace function public.complete_manual_task(p_task_id uuid, p_url text default null)
returns void
language plpgsql
security definer
set search_path = public
as $$
declare
  v_post uuid;
  v_platform text;
begin
  if not public.is_owner() then
    raise exception 'owner only';
  end if;
  update public.manual_tasks set status = 'done', done_at = now()
   where id = p_task_id and status = 'open'
  returning scheduled_post_id, platform into v_post, v_platform;
  if v_post is null then
    return;
  end if;
  insert into public.published_posts (scheduled_post_id, platform, url, visibility, method)
  values (v_post, v_platform, nullif(p_url, ''), 'public', 'manual')
  on conflict (scheduled_post_id) do update set url = coalesce(excluded.url, published_posts.url);
  update public.scheduled_posts set status = 'published', last_error = null where id = v_post;
  insert into public.audit_logs (actor, action, target_type, target_id, details)
  values ('owner', 'manual_task_done', 'manual_task', p_task_id::text, jsonb_build_object('url', p_url));
end;
$$;

-- Approve a whole package (the project and every variant of it and of its Shorts) in one transaction.
create or replace function public.approve_project(p_project_id uuid, p_notes text default null)
returns int
language plpgsql
security definer
set search_path = public
as $$
declare
  v_count int := 0;
  v_variant record;
begin
  if not public.is_owner() then
    raise exception 'owner only';
  end if;
  insert into public.approvals (target_type, target_id, decision, script_version_id, notes, decided_by)
  select 'project', p.id, 'approved', p.current_script_version_id, p_notes, auth.uid()
    from public.content_projects p
   where p.id = p_project_id or p.parent_project_id = p_project_id;
  update public.content_projects set status = 'approved', approved_script_version_id = current_script_version_id
   where (id = p_project_id or parent_project_id = p_project_id)
     and status in ('ready_for_review', 'needs_attention');
  for v_variant in
    select v.id from public.content_variants v join public.content_projects p on p.id = v.project_id
     where (p.id = p_project_id or p.parent_project_id = p_project_id)
       and v.status in ('ready_for_review', 'needs_attention')
  loop
    insert into public.approvals (target_type, target_id, decision, decided_by)
    values ('variant', v_variant.id, 'approved', auth.uid());
    update public.content_variants set status = 'approved' where id = v_variant.id;
    v_count := v_count + 1;
  end loop;
  return v_count;
end;
$$;

revoke all on function public.complete_manual_task(uuid, text) from public, anon;
grant execute on function public.complete_manual_task(uuid, text) to authenticated;
revoke all on function public.approve_project(uuid, text) from public, anon;
grant execute on function public.approve_project(uuid, text) to authenticated;

-- Final-quality file for posts the owner must upload by hand (expires with the media retention rules).
alter table public.manual_tasks add column if not exists asset_key text;
