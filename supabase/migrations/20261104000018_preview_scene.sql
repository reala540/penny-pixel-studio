-- Owners can preview one scene of a script on its own (for example an animated scene) without rebuilding the whole
-- video. It only renders a short file; nothing is approved, published or replaced. Also: the Freesound key.

create or replace function public.enqueue_owner_job(p_job_type text, p_project_id uuid default null, p_input jsonb default '{}')
returns uuid language plpgsql security definer set search_path=public as $$
declare found_id uuid; fingerprint text;
begin
  if not public.is_owner() then raise exception 'owner only'; end if;
  if p_job_type not in ('regenerate_script','rerender_preview','regenerate_thumbnails','recheck_project',
    'run_research','run_production','run_mission','generate_ideas','refine_idea','auto_review','produce_idea','check_providers','remake_shorts','preview_scene')
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
       'run_mission','regenerate_script','rerender_preview','regenerate_thumbnails','recheck_project','auto_review','produce_idea','check_providers','remake_shorts','preview_scene')
       and j.status in ('completed','failed','cancelled','blocked','needs_review')
    union all select 'note',n.created_at,'note:'||n.id,to_jsonb(n) from notifications n
    union all select 'audit',a.created_at,'audit:'||a.id,to_jsonb(a) from audit_logs a
      where a.action in ('auto_review_post_on','auto_review_post_off','posting_schedule_changed','setup_value_saved',
       'setup_value_removed','paused','resumed','telegram_linked','cancel_requested')
  ) e order by e.at desc,e.eid desc limit least(greatest(p_limit,1),150) offset greatest(p_offset,0);
end $$;
revoke all on function public.studio_activity(integer,integer) from public,anon;
grant execute on function public.studio_activity(integer,integer) to authenticated;

-- the Freesound key (sound effects for animated scenes) can be saved from the Setup page like the other keys
alter table public.app_secrets drop constraint if exists app_secrets_name_check;
alter table public.app_secrets add constraint app_secrets_name_check check (name in (
  'TELEGRAM_BOT_TOKEN', 'TELEGRAM_WEBHOOK_SECRET',
  'GOOGLE_CLIENT_ID', 'GOOGLE_CLIENT_SECRET', 'FACEBOOK_APP_ID', 'FACEBOOK_APP_SECRET',
  'TIKTOK_CLIENT_KEY', 'TIKTOK_CLIENT_SECRET', 'X_CLIENT_ID', 'X_CLIENT_SECRET',
  'YOUTUBE_API_KEY', 'PEXELS_API_KEY', 'PIXABAY_API_KEY', 'FRED_API_KEY', 'SEC_USER_AGENT', 'FREESOUND_API_KEY'));

notify pgrst, 'reload schema';
