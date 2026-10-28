-- Shorts can be made again for a package, and manually posted texts show as published.
-- 1. owners can request 'remake_shorts' (new Shorts from a package's own checked facts; nothing is posted until
--    the owner approves them); it appears in Activity like other requests.
-- 2. marking a copy-and-paste post as done also marks its post text published, and earlier ones are corrected.

create or replace function public.enqueue_owner_job(p_job_type text, p_project_id uuid default null, p_input jsonb default '{}')
returns uuid language plpgsql security definer set search_path=public as $$
declare found_id uuid; fingerprint text;
begin
  if not public.is_owner() then raise exception 'owner only'; end if;
  if p_job_type not in ('regenerate_script','rerender_preview','regenerate_thumbnails','recheck_project',
    'run_research','run_production','run_mission','generate_ideas','refine_idea','auto_review','produce_idea','check_providers','remake_shorts')
    or jsonb_typeof(p_input) <> 'object' then raise exception 'unsupported owner job'; end if;
  fingerprint := p_job_type || ':' || coalesce(p_project_id::text,'') || ':' || p_input::text;
  perform pg_advisory_xact_lock(hashtextextended(fingerprint,0));
  select id into found_id from generation_jobs where job_type=p_job_type
    and project_id is not distinct from p_project_id and input=p_input and requested_by='owner'
    and status in ('queued','running','retrying') order by created_at desc limit 1;
  if found_id is null then
    insert into generation_jobs(job_type,project_id,input,idempotency_key,status,requested_by)
      values(p_job_type,p_project_id,p_input,'owner:'||p_job_type||':'||gen_random_uuid(),'queued','owner')
      returning id into found_id;
  end if;
  return found_id;
end $$;
revoke all on function public.enqueue_owner_job(text,uuid,jsonb) from public,anon;
grant execute on function public.enqueue_owner_job(text,uuid,jsonb) to authenticated;

create or replace function public.studio_activity(p_offset integer default 0,p_limit integer default 150)
returns table(kind text,record jsonb) language plpgsql security definer set search_path=public as $$
begin
  if not public.is_owner() then raise exception 'owner only'; end if;
  return query select e.kind,e.payload from (
    select 'job'::text kind, coalesce(j.finished_at,j.updated_at) at, 'job:'||j.id eid,
      to_jsonb(j)||jsonb_build_object('content_projects',jsonb_build_object('title',p.title)) payload
      from generation_jobs j left join content_projects p on p.id=j.project_id
      where j.job_type in ('generate_ideas','refine_idea','run_research','weekly_research','run_production','weekly_production',
       'run_mission','regenerate_script','rerender_preview','regenerate_thumbnails','recheck_project','auto_review','produce_idea','check_providers','remake_shorts')
       and j.status in ('completed','failed','cancelled','blocked','needs_review')
    union all select 'note',n.created_at,'note:'||n.id,to_jsonb(n) from notifications n
    union all select 'audit',a.created_at,'audit:'||a.id,to_jsonb(a) from audit_logs a
      where a.action in ('auto_review_post_on','auto_review_post_off','posting_schedule_changed','setup_value_saved',
       'setup_value_removed','paused','resumed','telegram_linked','cancel_requested')
  ) e order by e.at desc,e.eid desc limit least(greatest(p_limit,1),150) offset greatest(p_offset,0);
end $$;
revoke all on function public.studio_activity(integer,integer) from public,anon;
grant execute on function public.studio_activity(integer,integer) to authenticated;

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
  -- the post text is published too, so the package shows it as posted rather than still "approved"
  update public.content_variants set status = 'published'
   where id = (select variant_id from public.scheduled_posts where id = v_post) and status = 'approved';
  insert into public.audit_logs (actor, action, target_type, target_id, details)
  values ('owner', 'manual_task_done', 'manual_task', p_task_id::text, jsonb_build_object('url', p_url));
end;
$$;
revoke all on function public.complete_manual_task(uuid, text) from public, anon;
grant execute on function public.complete_manual_task(uuid, text) to authenticated;

update public.content_variants v set status = 'published'
  from public.scheduled_posts sp
 where sp.variant_id = v.id and sp.status = 'published' and v.status = 'approved';

notify pgrst, 'reload schema';
