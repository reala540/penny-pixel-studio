-- v2.4: Auto Review & Post. Default OFF. When ON, the engine may approve a package that passes every automatic
-- check; the existing publish runner then posts it at its scheduled times (same duplicate and destination guards).

-- Who approved: the owner, or the automatic review.
alter table public.approvals
  add column source text not null default 'owner' check (source in ('owner', 'auto_review'));

-- One automatic review per script version, with its full result (audit trail, and no double reviews).
create table public.auto_reviews (
  id uuid primary key default gen_random_uuid(),
  project_id uuid not null references public.content_projects(id) on delete cascade,
  script_version_id uuid,
  verdict text not null check (verdict in ('approved', 'needs_review', 'error', 'skipped')),
  checks jsonb not null default '[]'::jsonb,   -- [{name, ok, detail}]
  reasons jsonb not null default '[]'::jsonb,  -- plain-language reasons for a person
  reviewer text,                               -- provider/model of the AI policy review
  confidence numeric(4,3),
  posts_scheduled int not null default 0,
  created_at timestamptz not null default now(),
  unique (project_id, script_version_id)
);
create index auto_reviews_created_idx on public.auto_reviews (created_at desc);
alter table public.auto_reviews enable row level security;
create policy owner_select on public.auto_reviews for select to authenticated using ((select public.is_owner()));
revoke insert, update, delete on public.auto_reviews from anon, authenticated;

-- The single switch. Callable by the owner (dashboard) and the Worker (Telegram, service role).
-- Turning it OFF returns auto-approved posts that haven't started publishing to "waiting for approval".
create or replace function public.set_auto_review_post(p_on boolean, p_actor text default 'owner')
returns jsonb
language plpgsql
security definer
set search_path = public
as $$
declare
  v_reverted int := 0;
  v_was boolean;
  v_claims jsonb := nullif(current_setting('request.jwt.claims', true), '')::jsonb;
  v_role text := coalesce(nullif(current_setting('request.jwt.claim.role', true), ''), v_claims->>'role', '');
begin
  -- current_user is the function owner inside SECURITY DEFINER, so check who is really calling:
  -- the signed-in owner, the Worker (service-role token), or the engine's direct database session (no token).
  if not (public.is_owner() or v_role = 'service_role' or (session_user = 'postgres' and v_claims is null)) then
    raise exception 'owner only';
  end if;
  if p_actor not in ('owner', 'telegram') then
    raise exception 'unknown actor';
  end if;
  select coalesce((value)::text = 'true', false) into v_was from public.settings where key = 'auto_review_post';
  insert into public.settings (key, value) values ('auto_review_post', to_jsonb(p_on))
  on conflict (key) do update set value = excluded.value, updated_at = now();
  if not p_on then
    with auto as (
      select distinct a.target_id from public.approvals a
       where a.target_type = 'variant' and a.decision = 'approved' and a.source = 'auto_review'
    ), back as (
      update public.content_variants v set status = 'ready_for_review'
        from auto
       where v.id = auto.target_id and v.status = 'approved'
         and not exists (select 1 from public.scheduled_posts sp
                          where sp.variant_id = v.id and sp.status in ('publishing', 'published'))
      returning v.project_id
    )
    select count(*) into v_reverted from back;
    update public.content_projects p set status = 'ready_for_review'
     where p.status = 'approved'
       and exists (select 1 from public.approvals a where a.target_type = 'project' and a.target_id = p.id
                     and a.source = 'auto_review')
       and not exists (select 1 from public.content_variants v where v.project_id = p.id and v.status in ('approved', 'published'));
  end if;
  insert into public.audit_logs (actor, action, target_type, target_id, details)
  values (p_actor, 'auto_review_post_' || case when p_on then 'on' else 'off' end, 'setting', 'auto_review_post',
          jsonb_build_object('was', coalesce(v_was, false), 'now', p_on, 'reverted_posts', v_reverted));
  return jsonb_build_object('on', p_on, 'was', coalesce(v_was, false), 'reverted_posts', v_reverted);
end;
$$;
revoke all on function public.set_auto_review_post(boolean, text) from public, anon;
grant execute on function public.set_auto_review_post(boolean, text) to authenticated, service_role;

-- The owner may still edit other settings, but this one only through the function above (audited, reverts on OFF).
drop policy if exists owner_update on public.settings;
create policy owner_update on public.settings for update to authenticated
  using ((select public.is_owner()) and key <> 'auto_review_post')
  with check ((select public.is_owner()) and key <> 'auto_review_post');
drop policy if exists owner_insert on public.settings;
create policy owner_insert on public.settings for insert to authenticated
  with check ((select public.is_owner()) and key <> 'auto_review_post');

-- Make the new function visible to the API straight away.
notify pgrst, 'reload schema';
