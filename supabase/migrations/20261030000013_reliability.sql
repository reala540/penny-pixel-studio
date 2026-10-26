-- Additive reliability support. No content or credentials are removed.
alter table public.generation_jobs add column cancel_requested_at timestamptz;
alter table public.notifications add column delivery_attempts integer not null default 0;
-- Leave historic unsent events unqueued: upgrading must not flood the owner with old alerts.
alter table public.notifications add column next_delivery_at timestamptz;
alter table public.notifications alter column next_delivery_at set default now();
alter table public.notifications add column delivery_locked_until timestamptz;
create index notifications_delivery_due on public.notifications (next_delivery_at)
  where sent_at is null and delivery_attempts < 5;

-- Atomic patches avoid overwriting unrelated fields from another tab.
create function public.patch_studio_setting(p_key text, p_patch jsonb, p_expected jsonb default null)
returns jsonb language plpgsql security definer set search_path = public as $$
declare old_value jsonb; next_value jsonb;
begin
  if not public.is_owner() then raise exception 'owner only'; end if;
  if p_key not in ('idea_generator','auto_review_fix','auto_replace','ui_cleared')
     or jsonb_typeof(p_patch) <> 'object' then raise exception 'unsupported setting patch'; end if;
  insert into settings(key,value) values(p_key,'{}') on conflict do nothing;
  select value into old_value from settings where key=p_key for update;
  if p_expected is not null and not old_value @> p_expected then
    raise exception 'This setting changed elsewhere. Reload before trying again.';
  end if;
  next_value := old_value || p_patch;
  update settings set value=next_value, updated_at=now() where key=p_key;
  insert into audit_logs(actor,action,target_type,target_id,details)
    values('owner','setting_changed','setting',p_key,jsonb_build_object('fields',p_patch));
  return next_value;
end $$;
revoke all on function public.patch_studio_setting(text,jsonb,jsonb) from public,anon;
grant execute on function public.patch_studio_setting(text,jsonb,jsonb) to authenticated;

-- A stable request identity deduplicates active work, not just double-clicks in one tab.
create function public.enqueue_owner_job(p_job_type text, p_project_id uuid default null, p_input jsonb default '{}')
returns uuid language plpgsql security definer set search_path=public as $$
declare found_id uuid; fingerprint text;
begin
  if not public.is_owner() then raise exception 'owner only'; end if;
  if p_job_type not in ('regenerate_script','rerender_preview','regenerate_thumbnails','recheck_project',
    'run_research','run_production','run_mission','generate_ideas','refine_idea','auto_review','produce_idea','check_providers')
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

-- Cancellation is cooperative and scoped to one owner request. No files or projects are erased.
create function public.cancel_owner_job(p_job_id uuid) returns text
language plpgsql security definer set search_path=public as $$
declare j generation_jobs; result text;
begin
  if not public.is_owner() then raise exception 'owner only'; end if;
  select * into j from generation_jobs where id=p_job_id for update;
  if not found or j.requested_by <> 'owner' then raise exception 'Choose an owner-requested job'; end if;
  if j.status not in ('queued','running','retrying') then return j.status; end if;
  result := case when j.status='running' then 'running' else 'cancelled' end;
  update generation_jobs set cancel_requested_at=now(), status=result,
    finished_at=case when result='cancelled' then now() else finished_at end where id=j.id;
  insert into audit_logs(actor,action,target_type,target_id,details)
    values('owner','cancel_requested','generation_job',j.id::text,'{}');
  if result='cancelled' then
    insert into notifications(kind,title,body,dedupe_key) values('job_cancelled','Work cancelled',
      'This queued request was cancelled. Saved content and other projects were kept.','cancelled:'||j.id)
      on conflict(dedupe_key) do nothing;
  end if;
  return case when result='running' then 'stopping' else result end;
end $$;
revoke all on function public.cancel_owner_job(uuid) from public,anon;
grant execute on function public.cancel_owner_job(uuid) to authenticated;

-- All owner rescheduling paths use the same account lock and clash check.
create function public.reschedule_post(p_post_id uuid, p_when timestamptz) returns void
language plpgsql security definer set search_path=public as $$
declare p scheduled_posts;
begin
  if not public.is_owner() then raise exception 'owner only'; end if;
  select * into p from scheduled_posts where id=p_post_id;
  if not found then raise exception 'Post no longer exists'; end if;
  perform 1 from social_accounts where id=p.social_account_id for update;
  select * into p from scheduled_posts where id=p_post_id for update;
  if p.status not in ('scheduled','pending_approval') then raise exception 'This post can no longer be moved'; end if;
  if p_when is null or p_when <= now() then raise exception 'Choose a future time'; end if;
  if exists(select 1 from scheduled_posts where social_account_id=p.social_account_id and id<>p.id
    and status not in ('cancelled','failed') and abs(extract(epoch from scheduled_at-p_when))<1800) then
    raise exception 'Another post on this account is within 30 minutes. Choose a different time.';
  end if;
  update scheduled_posts set scheduled_at=p_when where id=p.id;
end $$;
revoke all on function public.reschedule_post(uuid,timestamptz) from public,anon;
grant execute on function public.reschedule_post(uuid,timestamptz) to authenticated;

-- Pausing through the dashboard uses a database setting, so persist its notification in the same transaction.
create function public.notify_dashboard_pause() returns trigger
language plpgsql security definer set search_path=public as $$
begin
  if new.key='paused' and auth.uid() is not null and
     (tg_op='INSERT' or old.value is distinct from new.value) then
    insert into notifications(kind,title,body,link,dedupe_key)
    values('publishing_pause',case when new.value='true'::jsonb then 'Publishing paused' else 'Publishing resumed' end,
      'Open the dashboard to view current publishing status.',null,
      'pause:'||gen_random_uuid());
  end if;
  return new;
end $$;
create trigger notify_dashboard_pause after insert or update on public.settings
  for each row execute function public.notify_dashboard_pause();

-- Owner-scoped recovery bookmarks. Credentials remain in the existing encrypted secret store.
create table public.studio_drafts (
  owner_id uuid not null default auth.uid(),
  id text not null,
  payload jsonb,
  revision integer not null default 1,
  updated_at timestamptz not null default now(),
  primary key(owner_id,id)
);
alter table public.studio_drafts enable row level security;
create policy owner_draft_read on public.studio_drafts for select to authenticated
  using (public.is_owner() and owner_id=auth.uid());
revoke all on public.studio_drafts from public,anon;
grant select on public.studio_drafts to authenticated;
revoke insert,update,delete on public.studio_drafts from public,anon,authenticated;
create function public.save_studio_draft(p_id text,p_payload jsonb,p_expected integer default 0)
returns jsonb language plpgsql security definer set search_path=public as $$
declare row studio_drafts;
begin
  if not public.is_owner() or auth.uid() is null then raise exception 'owner only'; end if;
  if length(p_id)>64 or length(p_id)<1 then raise exception 'Invalid draft id'; end if;
  if p_payload is not null and (p_payload->>'id' is distinct from p_id or jsonb_typeof(p_payload)<>'object' or octet_length(p_payload::text)>16000 or
    (select bool_or(k not in ('id','rev','updatedAt','step','channel','kind','ideaId','ideaTitle','own','depth')) from jsonb_object_keys(p_payload) k)) then
    raise exception 'Only creation choices and non-secret idea text can be saved';
  end if;
  if p_payload::text ~* '(sk-|gsk_|ghp_|github_pat_|AIza|Bearer )[A-Za-z0-9_-]{12,}' then
    raise exception 'Do not save credentials in drafts';
  end if;
  perform pg_advisory_xact_lock(hashtextextended(auth.uid()::text||p_id,0));
  select * into row from studio_drafts where owner_id=auth.uid() and id=p_id for update;
  if coalesce(row.revision,0)<>p_expected then return jsonb_build_object('conflict',true,'revision',row.revision); end if;
  insert into studio_drafts(owner_id,id,payload,revision) values(auth.uid(),p_id,p_payload,1)
    on conflict(owner_id,id) do update set payload=excluded.payload,revision=studio_drafts.revision+1,updated_at=now()
    returning * into row;
  return jsonb_build_object('revision',row.revision);
end $$;
revoke all on function public.save_studio_draft(text,jsonb,integer) from public,anon;
grant execute on function public.save_studio_draft(text,jsonb,integer) to authenticated;

-- Refuse stale schedule saves rather than overwriting another device's edits.
create function public.save_posting_schedule(p_account_id uuid,p_schedule jsonb,p_expected jsonb,p_move boolean default false)
returns jsonb language plpgsql security definer set search_path=public as $$
declare current_schedule jsonb;
begin
  if not public.is_owner() then raise exception 'owner only'; end if;
  select jsonb_build_object('weekly_targets',weekly_targets,'enabled',enabled) into current_schedule
    from social_accounts where id=p_account_id for update;
  if current_schedule is distinct from p_expected then
    raise exception 'This schedule changed elsewhere. Reload before saving your edits.';
  end if;
  return public.set_posting_schedule(p_account_id,p_schedule,p_move);
end $$;
revoke all on function public.save_posting_schedule(uuid,jsonb,jsonb,boolean) from public,anon;
grant execute on function public.save_posting_schedule(uuid,jsonb,jsonb,boolean) to authenticated;

-- One globally ordered page, rather than separately truncating each source of the Activity timeline.
create function public.studio_activity(p_offset integer default 0,p_limit integer default 150)
returns table(kind text,record jsonb) language plpgsql security definer set search_path=public as $$
begin
  if not public.is_owner() then raise exception 'owner only'; end if;
  return query select e.kind,e.payload from (
    select 'job'::text kind, coalesce(j.finished_at,j.updated_at) at, 'job:'||j.id eid,
      to_jsonb(j)||jsonb_build_object('content_projects',jsonb_build_object('title',p.title)) payload
      from generation_jobs j left join content_projects p on p.id=j.project_id
      where j.job_type in ('generate_ideas','refine_idea','run_research','weekly_research','run_production','weekly_production',
       'run_mission','regenerate_script','rerender_preview','regenerate_thumbnails','recheck_project','auto_review','produce_idea','check_providers')
       and j.status in ('completed','failed','cancelled','blocked','needs_review')
    union all select 'note',n.created_at,'note:'||n.id,to_jsonb(n) from notifications n
    union all select 'audit',a.created_at,'audit:'||a.id,to_jsonb(a) from audit_logs a
      where a.action in ('auto_review_post_on','auto_review_post_off','posting_schedule_changed','setup_value_saved',
       'setup_value_removed','paused','resumed','telegram_linked','cancel_requested')
  ) e order by e.at desc,e.eid desc limit least(greatest(p_limit,1),150) offset greatest(p_offset,0);
end $$;
revoke all on function public.studio_activity(integer,integer) from public,anon;
grant execute on function public.studio_activity(integer,integer) to authenticated;
