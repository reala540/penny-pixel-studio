-- Quality pack.
-- 1. Owner approval of a package with unsupported or contradicted facts, or parts that need attention, needs a written
--    reason. The reason is kept with the approval and in the audit log (both can't be edited).
-- 2. Facebook Reels and text posts can have their own days and times (reel_days/reel_times, text_days/text_times);
--    without them they use the Page's posting days and times, exactly as before. "Move" keeps Stories 3 hours after
--    their Reel.
-- Existing approvals, schedules and posts are unchanged.

create or replace function public.approve_project(p_project_id uuid, p_notes text default null,
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
  v_bad int;
  v_attention int;
  v_reason text := nullif(btrim(coalesce(p_notes, '')), '');
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
  select count(*) into v_bad from public.research_claims c join public.content_projects p on p.current_script_version_id = c.script_version_id
   where p.id = any(v_ids) and c.status in ('unsupported', 'contradicted');
  select count(*) into v_attention from public.content_projects where id = any(v_ids) and status = 'needs_attention';
  if (v_bad > 0 or v_attention > 0) and (v_reason is null or length(v_reason) < 10) then
    raise exception 'This package still has problems (% unsupported or contradicted fact(s), % part(s) needing attention). Fix them, or write why you are approving anyway (at least 10 characters).', v_bad, v_attention;
  end if;
  insert into public.approvals (target_type, target_id, decision, script_version_id, notes, decided_by)
  select 'project', p.id, 'approved', p.current_script_version_id, v_reason, auth.uid()
    from public.content_projects p where p.id = any(v_ids);
  if v_bad > 0 or v_attention > 0 then
    insert into public.audit_logs (actor, action, target_type, target_id, details)
    values ('owner', 'approved_with_problems', 'content_project', p_project_id::text,
            jsonb_build_object('title', v_head.title, 'unsupported_facts', v_bad, 'parts_needing_attention', v_attention,
                               'reason', v_reason, 'script_version_id', v_head.current_script_version_id));
  end if;
  update public.content_projects set status = 'approved', approved_script_version_id = current_script_version_id
   where id = any(v_ids);
  for v_variant in
    select v.id from public.content_variants v
     where v.project_id = any(v_ids) and v.status in ('ready_for_review', 'needs_attention')
  loop
    insert into public.approvals (target_type, target_id, decision, notes, decided_by)
    values ('variant', v_variant.id, 'approved', v_reason, auth.uid());
    update public.content_variants set status = 'approved' where id = v_variant.id;
    v_count := v_count + 1;
  end loop;
  return v_count;
end;
$$;
revoke all on function public.approve_project(uuid, text, uuid) from public, anon;
grant execute on function public.approve_project(uuid, text, uuid) to authenticated;

-- same function as migration 16, with Facebook's own Reel and text-post times
create or replace function public.set_posting_schedule(p_account_id uuid, p_schedule jsonb, p_move boolean default false)
returns jsonb
language plpgsql
security definer
set search_path = public
as $$
declare
  v_acc social_accounts%rowtype;
  v_old jsonb;
  v_new jsonb;
  v_days constant text[] := array['mon','tue','wed','thu','fri','sat','sun'];
  v_kinds text[];
  v_key text;
  v_list text[];
  v_n int;
  v_tz text := coalesce((select value #>> '{}' from settings where key = 'timezone'), 'Africa/Nairobi');
  v_moved int := 0;
  r record;
  v_group text;
  v_slots timestamptz[];
  v_i int;
  v_src text;
begin
  if not public.is_owner() then
    raise exception 'owner only';
  end if;
  select * into v_acc from social_accounts where id = p_account_id;
  if not found then
    raise exception 'unknown account';
  end if;
  v_kinds := case v_acc.platform when 'youtube' then array['long_video','short_video']
                                 when 'facebook' then array['reel','story','text_post','long_video']
                                 when 'tiktok' then array['short_video']
                                 else array['text_post'] end;
  v_old := v_acc.weekly_targets;
  v_new := v_old;
  foreach v_key in array array['posting_days','shorts_days','reel_days','text_days'] loop
    if p_schedule ? v_key then
      select coalesce(array_agg(distinct lower(x)), '{}') into v_list from jsonb_array_elements_text(p_schedule -> v_key) x;
      if not v_list <@ v_days then
        raise exception 'days must be mon, tue, wed, thu, fri, sat or sun';
      end if;
      v_new := jsonb_set(v_new, array[v_key], to_jsonb((select coalesce(array_agg(d order by array_position(v_days, d)), '{}')
                                                         from unnest(v_list) d)));
    end if;
  end loop;
  foreach v_key in array array['posting_times','shorts_times','reel_times','text_times'] loop
    if p_schedule ? v_key then
      select coalesce(array_agg(distinct x order by x), '{}') into v_list from jsonb_array_elements_text(p_schedule -> v_key) x;
      if exists (select 1 from unnest(v_list) t where t !~ '^([01][0-9]|2[0-3]):[0-5][0-9]$') then
        raise exception 'times must look like 18:00';
      end if;
      if cardinality(v_list) > 4 then
        raise exception 'at most 4 times a day';
      end if;
      v_new := jsonb_set(v_new, array[v_key], to_jsonb(v_list));
    end if;
  end loop;
  if v_acc.platform <> 'youtube' and (p_schedule ? 'shorts_days' or p_schedule ? 'shorts_times') then
    raise exception 'separate Shorts times are only for YouTube';
  end if;
  if v_acc.platform <> 'facebook' and (p_schedule ?| array['reel_days','reel_times','text_days','text_times']) then
    raise exception 'separate Reel and text-post times are only for Facebook';
  end if;
  for v_key in select jsonb_object_keys(coalesce(p_schedule -> 'targets', '{}'::jsonb)) loop
    if not v_key = any(v_kinds) then
      raise exception '% is not a post type for %', v_key, v_acc.platform;
    end if;
    v_n := (p_schedule -> 'targets' ->> v_key)::int;
    if v_n is null or v_n < 0 or v_n > 14 then
      raise exception 'posts per week must be between 0 and 14';
    end if;
    v_new := jsonb_set(v_new, array[v_key], to_jsonb(v_n));
  end loop;
  update social_accounts set weekly_targets = v_new,
         enabled = coalesce((p_schedule ->> 'enabled')::boolean, enabled)
   where id = p_account_id;

  if p_move then
    -- Waiting posts move to the new slots in their current order; anything publishing or published stays put.
    -- Facebook: Reels and text posts use their own days and times when set (else the Page's); Stories follow their Reel
    for v_group in select unnest(case v_acc.platform when 'youtube' then array['posting','shorts']
                                                      when 'facebook' then array['reel','text','posting']
                                                      else array['posting'] end) loop
      v_src := case when v_group in ('reel','text')
                     and jsonb_array_length(coalesce(v_new -> (v_group || '_days'), '[]')) > 0
                     and jsonb_array_length(coalesce(v_new -> (v_group || '_times'), '[]')) > 0
                    then v_group when v_group in ('reel','text') then 'posting' else v_group end;
      select array_agg(s) into v_slots from public.schedule_slots(
        array(select jsonb_array_elements_text(coalesce(v_new -> (v_src || '_days'), '[]'))),
        array(select jsonb_array_elements_text(coalesce(v_new -> (v_src || '_times'), '[]'))),
        v_tz, now() + interval '15 minutes', 200) s;
      v_i := 0;
      for r in select sp.id from scheduled_posts sp join content_variants v on v.id = sp.variant_id
                where sp.social_account_id = p_account_id and sp.status in ('pending_approval', 'scheduled')
                  and sp.scheduled_at > now()
                  and (v_acc.platform <> 'youtube' or (v_group = 'shorts') = (v.kind = 'short_video'))
                  and (v_acc.platform <> 'facebook' or case v_group when 'reel' then v.kind = 'reel'
                                                                  when 'text' then v.kind = 'text_post'
                                                                  else v.kind not in ('reel','text_post','story') end)
                order by sp.scheduled_at loop
        v_i := v_i + 1;
        exit when v_slots is null or v_i > cardinality(v_slots);
        update scheduled_posts set scheduled_at = v_slots[v_i] where id = r.id and scheduled_at is distinct from v_slots[v_i];
        if found then v_moved := v_moved + 1; end if;
      end loop;
    end loop;
    if v_acc.platform = 'facebook' then  -- each waiting Story stays STORY_DELAY (3 hours) after its Reel
      update scheduled_posts st set scheduled_at = reel.scheduled_at + interval '3 hours'
        from content_variants sv, scheduled_posts reel, content_variants rv
       where sv.id = st.variant_id and sv.kind = 'story' and st.social_account_id = p_account_id
         and st.status in ('pending_approval', 'scheduled') and st.scheduled_at > now()
         and rv.id = reel.variant_id and rv.kind = 'reel' and rv.project_id = sv.project_id
         and reel.social_account_id = p_account_id and reel.status in ('pending_approval', 'scheduled')
         and st.scheduled_at is distinct from reel.scheduled_at + interval '3 hours';
    end if;
  end if;

  insert into audit_logs (actor, action, target_type, target_id, details)
  values ('owner', 'posting_schedule_changed', 'social_account', p_account_id::text,
          jsonb_build_object('account', v_acc.label, 'before', v_old, 'after', v_new,
                             'enabled', coalesce((p_schedule ->> 'enabled')::boolean, v_acc.enabled), 'moved_posts', v_moved));
  return jsonb_build_object('weekly_targets', v_new, 'moved_posts', v_moved);
end;
$$;
revoke all on function public.set_posting_schedule(uuid, jsonb, boolean) from public, anon;
grant execute on function public.set_posting_schedule(uuid, jsonb, boolean) to authenticated;
alter function public.set_posting_schedule(uuid, jsonb, boolean) set search_path = public;

notify pgrst, 'reload schema';
