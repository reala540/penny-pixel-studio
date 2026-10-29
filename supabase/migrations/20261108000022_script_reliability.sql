-- Script reliability.
-- 1. A claim can be a general principle ("inflation reduces what cash can buy"): checked by code to state no figure,
--    name or date, and shown as "general" instead of failing as an unsourced fact.
-- 2. The owner can recheck and repair an unfinished package with the corrected workflow (repair_package): a new
--    script version is saved (the old ones are kept), only the preview is re-rendered, and nothing is approved,
--    scheduled again or published. It appears in Activity like other requests.

alter table public.script_versions drop constraint if exists script_versions_origin_check;
alter table public.script_versions add constraint script_versions_origin_check
  check (origin in ('ai','owner_edit','rewrite','repair'));

alter table public.research_claims drop constraint if exists research_claims_status_check;
alter table public.research_claims add constraint research_claims_status_check
  check (status in ('unverified','supported','partially_supported','unsupported','contradicted','opinion','stale','general'));

create or replace function public.enqueue_owner_job(p_job_type text, p_project_id uuid default null, p_input jsonb default '{}')
returns uuid language plpgsql security definer set search_path=public as $$
declare found_id uuid; fingerprint text;
begin
  if not public.is_owner() then raise exception 'owner only'; end if;
  if p_job_type not in ('regenerate_script','rerender_preview','regenerate_thumbnails','recheck_project',
    'run_research','run_production','run_mission','generate_ideas','refine_idea','auto_review','produce_idea','check_providers','remake_shorts','preview_scene','repair_package')
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
       'run_mission','regenerate_script','rerender_preview','regenerate_thumbnails','recheck_project','auto_review','produce_idea','check_providers','remake_shorts','preview_scene','repair_package')
       and j.status in ('completed','failed','cancelled','blocked','needs_review')
    union all select 'note',n.created_at,'note:'||n.id,to_jsonb(n) from notifications n
    union all select 'audit',a.created_at,'audit:'||a.id,to_jsonb(a) from audit_logs a
      where a.action in ('auto_review_post_on','auto_review_post_off','posting_schedule_changed','setup_value_saved',
       'setup_value_removed','paused','resumed','telegram_linked','cancel_requested')
  ) e order by e.at desc,e.eid desc limit least(greatest(p_limit,1),150) offset greatest(p_offset,0);
end $$;
revoke all on function public.studio_activity(integer,integer) from public,anon;
grant execute on function public.studio_activity(integer,integer) to authenticated;

notify pgrst, 'reload schema';
