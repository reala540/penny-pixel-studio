-- Owner-only automation funnel; stages count distinct parent packages, never review attempts.
create or replace function public.studio_automation_funnel() returns jsonb
language plpgsql stable security invoker set search_path=public as $$
declare result jsonb;
begin
 if not public.is_owner() then raise exception 'owner only'; end if;
 with reviewed as (select distinct coalesce(p.parent_project_id,p.id) id from auto_reviews a join content_projects p on p.id=a.project_id),
 repaired as (select distinct coalesce(p.parent_project_id,p.id) id from generation_jobs j join content_projects p on p.id=j.project_id where j.input->>'auto_fix'='true'),
 approved as (select distinct coalesce(p.parent_project_id,p.id) id from approvals a join content_projects p on p.id=a.target_id where a.target_type='project' and a.decision='approved' and a.source='auto_review'),
 public_packages as (select distinct coalesce(p.parent_project_id,p.id) id from published_posts pp join scheduled_posts sp on sp.id=pp.scheduled_post_id join content_variants v on v.id=sp.variant_id join content_projects p on p.id=v.project_id
 where pp.visibility='public' and pp.method in ('api','api_draft') and (select a.source from approvals a where a.target_type='project' and a.target_id=p.id and a.decision='approved' and a.decided_at<=pp.published_at order by a.decided_at desc,a.id desc limit 1)='auto_review')
 select jsonb_build_object('reviewed',(select count(*) from reviewed),'repair_started',(select count(*) from repaired),'approved',(select count(*) from approved),'public',(select count(*) from public_packages),
 'review_attempts',(select count(*) from auto_reviews),'repair_jobs',(select count(*) from generation_jobs where input->>'auto_fix'='true'),
 'repair_completed',(select count(*) from generation_jobs where input->>'auto_fix'='true' and status='completed'),
 'baseline',(select value from settings where key='automation_baseline_v2')) into result;
 return result;
end $$;
revoke all on function public.studio_automation_funnel() from public,anon;
grant execute on function public.studio_automation_funnel() to authenticated;
-- Frozen before new policy is activated; do not overwrite the comparison on subsequent runs.
insert into settings(key,value) select 'automation_baseline_v2',jsonb_build_object('at',now(),
 'reviewed',(select count(distinct project_id) from auto_reviews),'review_attempts',(select count(*) from auto_reviews),
 'repair_jobs',(select count(*) from generation_jobs where input->>'auto_fix'='true'),
 'approved',(select count(distinct target_id) from approvals where target_type='project' and source='auto_review' and decision='approved')) on conflict(key) do nothing;
notify pgrst,'reload schema';
-- Revisit existing holds once under the corrected policy; the switch itself remains unchanged.
insert into generation_jobs(job_type,idempotency_key,status,requested_by,input)
select 'auto_review','auto-review:recovery-v2','queued','owner','{"review_policy":"recovery_v2","recover_final_checks":true}'::jsonb
where exists(select 1 from settings where key='auto_review_post' and value='true'::jsonb)
on conflict(idempotency_key) do nothing;
