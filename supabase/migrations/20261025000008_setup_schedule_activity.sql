-- v2.5: setup wizard secrets, posting schedule editor, auto-fix attempts, live job progress.

-- Secrets saved from the dashboard Setup page. The Worker encrypts them (AES-256-GCM with TOKEN_ENCRYPTION_KEY)
-- before they arrive here; no client role can read or write this table (RLS on, no policies, no grants).
-- Only names the studio knows are accepted, so this can't become a general secret store.
create table public.app_secrets (
  name text primary key check (name in (
    'TELEGRAM_BOT_TOKEN', 'TELEGRAM_WEBHOOK_SECRET',
    'GOOGLE_CLIENT_ID', 'GOOGLE_CLIENT_SECRET', 'FACEBOOK_APP_ID', 'FACEBOOK_APP_SECRET',
    'TIKTOK_CLIENT_KEY', 'TIKTOK_CLIENT_SECRET', 'X_CLIENT_ID', 'X_CLIENT_SECRET',
    'YOUTUBE_API_KEY', 'PEXELS_API_KEY', 'PIXABAY_API_KEY', 'FRED_API_KEY', 'SEC_USER_AGENT')),
  ciphertext text not null,
  hint text,                                  -- last 4 characters, for display only
  updated_at timestamptz not null default now()
);
alter table public.app_secrets enable row level security;
revoke all on public.app_secrets from anon, authenticated;

-- What a running job is doing right now, for the Activity page: {"step": 3, "total": 6, "label": "Checking sources"}.
alter table public.generation_jobs add column progress jsonb;

-- Auto Review & Post can now fix a failed package and try again. Each attempt is its own row.
alter table public.auto_reviews drop constraint auto_reviews_verdict_check;
alter table public.auto_reviews add constraint auto_reviews_verdict_check
  check (verdict in ('approved', 'needs_review', 'error', 'skipped', 'fixing'));
alter table public.auto_reviews add column attempt int not null default 0;
alter table public.auto_reviews add column fix text;           -- what was changed for the next attempt
alter table public.auto_reviews drop constraint auto_reviews_project_id_script_version_id_key;
alter table public.auto_reviews add constraint auto_reviews_attempt_key unique (project_id, script_version_id, attempt);
create index auto_reviews_project_idx on public.auto_reviews (project_id, created_at desc);

-- Slots for a schedule: the next p_count local day/time combinations after p_from, in the studio timezone.
create or replace function public.schedule_slots(p_days text[], p_times text[], p_tz text, p_from timestamptz, p_count int)
returns setof timestamptz
language sql
stable
set search_path = public
as $$
  select s from (
    select ((((p_from at time zone p_tz)::date + d) + t::time) at time zone p_tz) as s
      from generate_series(0, 27) as d, unnest(p_times) as t
     where lower(to_char((p_from at time zone p_tz)::date + d, 'Dy')) = any(p_days)
  ) x
  where s > p_from
  order by s
  limit greatest(p_count, 0);
$$;
revoke all on function public.schedule_slots(text[], text[], text, timestamptz, int) from public, anon, authenticated;

-- The posting schedule editor. Validates everything, keeps other keys, can move waiting posts to the new slots.
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
begin
  if not public.is_owner() then
    raise exception 'owner only';
  end if;
  select * into v_acc from social_accounts where id = p_account_id;
  if not found then
    raise exception 'unknown account';
  end if;
  v_kinds := case v_acc.platform when 'youtube' then array['long_video','short_video']
                                 when 'facebook' then array['reel','text_post']
                                 when 'tiktok' then array['short_video']
                                 else array['text_post'] end;
  v_old := v_acc.weekly_targets;
  v_new := v_old;
  foreach v_key in array array['posting_days','shorts_days'] loop
    if p_schedule ? v_key then
      select coalesce(array_agg(distinct lower(x)), '{}') into v_list from jsonb_array_elements_text(p_schedule -> v_key) x;
      if not v_list <@ v_days then
        raise exception 'days must be mon, tue, wed, thu, fri, sat or sun';
      end if;
      v_new := jsonb_set(v_new, array[v_key], to_jsonb((select coalesce(array_agg(d order by array_position(v_days, d)), '{}')
                                                         from unnest(v_list) d)));
    end if;
  end loop;
  foreach v_key in array array['posting_times','shorts_times'] loop
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
    for v_group in select unnest(case when v_acc.platform = 'youtube' then array['posting','shorts'] else array['posting'] end) loop
      select array_agg(s) into v_slots from public.schedule_slots(
        array(select jsonb_array_elements_text(coalesce(v_new -> (v_group || '_days'), '[]'))),
        array(select jsonb_array_elements_text(coalesce(v_new -> (v_group || '_times'), '[]'))),
        v_tz, now() + interval '15 minutes', 200) s;
      v_i := 0;
      for r in select sp.id from scheduled_posts sp join content_variants v on v.id = sp.variant_id
                where sp.social_account_id = p_account_id and sp.status in ('pending_approval', 'scheduled')
                  and sp.scheduled_at > now()
                  and (v_acc.platform <> 'youtube' or (v_group = 'shorts') = (v.kind = 'short_video'))
                order by sp.scheduled_at loop
        v_i := v_i + 1;
        exit when v_slots is null or v_i > cardinality(v_slots);
        update scheduled_posts set scheduled_at = v_slots[v_i] where id = r.id and scheduled_at is distinct from v_slots[v_i];
        if found then v_moved := v_moved + 1; end if;
      end loop;
    end loop;
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

-- Make the new function visible to the API straight away.
notify pgrst, 'reload schema';
