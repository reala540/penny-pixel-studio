-- v2.7: a strict audit trail and strict protection against duplicate uploads, enforced by the database itself.

-- ---------------------------------------------------------------------------------------------------------------
-- 1. Audit log: append-only and tamper-evident.
-- Each row carries the hash of the row before it, so an edited or removed row breaks the chain
-- (public.audit_chain_problems() finds it). Rows can't be updated, deleted or truncated by anyone.

alter table public.audit_logs add column prev_hash text, add column row_hash text;

create or replace function public.audit_row_digest(p_prev text, p_actor text, p_action text, p_target_type text,
                                                   p_target_id text, p_details jsonb, p_created_at timestamptz)
returns text
language sql
immutable
as $$
  select encode(sha256(convert_to(concat_ws('|', p_prev, p_actor, p_action, coalesce(p_target_type, ''),
                                            coalesce(p_target_id, ''), p_details::text,
                                            to_char(p_created_at at time zone 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US')),
                                  'UTF8')), 'hex');
$$;

-- existing rows join the chain in order
do $$
declare
  r record;
  last text := 'genesis';
begin
  for r in select * from public.audit_logs order by id loop
    update public.audit_logs
       set prev_hash = last,
           row_hash = public.audit_row_digest(last, r.actor, r.action, r.target_type, r.target_id, r.details, r.created_at)
     where id = r.id
    returning row_hash into last;
  end loop;
end $$;

create or replace function public.audit_logs_chain()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
declare
  last text;
begin
  perform pg_advisory_xact_lock(hashtext('audit_logs_chain'));  -- one link at a time
  select row_hash into last from public.audit_logs order by id desc limit 1;
  new.created_at := coalesce(new.created_at, now());
  new.prev_hash := coalesce(last, 'genesis');
  new.row_hash := public.audit_row_digest(new.prev_hash, new.actor, new.action, new.target_type, new.target_id,
                                          new.details, new.created_at);
  return new;
end;
$$;
create trigger audit_logs_chain before insert on public.audit_logs
  for each row execute function public.audit_logs_chain();

create or replace function public.forbid_change()
returns trigger
language plpgsql
as $$
begin
  raise exception '% is permanent: its rows can''t be changed or removed', tg_table_name;
end;
$$;
create trigger audit_logs_append_only before update or delete on public.audit_logs
  for each row execute function public.forbid_change();
create trigger audit_logs_no_truncate before truncate on public.audit_logs
  for each statement execute function public.forbid_change();

alter table public.audit_logs alter column prev_hash set not null, alter column row_hash set not null;

-- Lists every row whose hash doesn't match: empty means the trail is intact.
create or replace function public.audit_chain_problems()
returns table (id bigint, problem text)
language sql
stable
security definer
set search_path = public
as $$
  with ordered as (
    select a.*, lag(a.row_hash) over (order by a.id) as expected_prev from public.audit_logs a
  )
  select o.id, case when o.prev_hash is distinct from coalesce(o.expected_prev, 'genesis') then 'chain broken before this row'
                    else 'row was changed' end
    from ordered o
   where o.prev_hash is distinct from coalesce(o.expected_prev, 'genesis')
      or o.row_hash <> public.audit_row_digest(o.prev_hash, o.actor, o.action, o.target_type, o.target_id, o.details,
                                               o.created_at)
   order by o.id;
$$;
revoke all on function public.audit_chain_problems() from public, anon;
grant execute on function public.audit_chain_problems() to authenticated;

-- Every important change is recorded automatically, whoever makes it (dashboard, Worker, engine or SQL).
create or replace function public.audit_actor()
returns text
language sql
stable
as $$
  select coalesce(nullif(current_setting('studio.actor', true), ''),
                  case when auth.uid() is not null then 'owner'
                       when current_user = 'service_role' then 'worker'
                       else 'engine' end);
$$;

create or replace function public.audit_status_change()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
declare
  d jsonb;
begin
  if tg_op = 'INSERT' then
    d := jsonb_build_object('status', new.status);
  else
    d := jsonb_build_object('from', old.status, 'to', new.status);
  end if;
  if tg_table_name = 'scheduled_posts' then
    d := d || jsonb_build_object('scheduled_at', new.scheduled_at, 'account', new.social_account_id, 'variant', new.variant_id);
    if tg_op = 'UPDATE' and old.scheduled_at is distinct from new.scheduled_at then
      d := d || jsonb_build_object('moved_from', old.scheduled_at);
    end if;
  elsif tg_table_name = 'content_projects' then
    d := d || jsonb_build_object('title', new.title);
  end if;
  insert into public.audit_logs (actor, action, target_type, target_id, details)
  values (public.audit_actor(), tg_table_name || '_' || lower(tg_op), tg_table_name, new.id::text, d);
  return new;
end;
$$;

create trigger audit_projects_insert after insert on public.content_projects
  for each row execute function public.audit_status_change();
create trigger audit_projects after update of status on public.content_projects
  for each row when (old.status is distinct from new.status) execute function public.audit_status_change();
create trigger audit_variants after update of status on public.content_variants
  for each row when (old.status is distinct from new.status) execute function public.audit_status_change();
create trigger audit_scheduled_posts_insert after insert on public.scheduled_posts
  for each row execute function public.audit_status_change();
create trigger audit_scheduled_posts after update of status, scheduled_at on public.scheduled_posts
  for each row when (old.status is distinct from new.status or old.scheduled_at is distinct from new.scheduled_at)
  execute function public.audit_status_change();

-- ---------------------------------------------------------------------------------------------------------------
-- 2. A publish attempt is written down BEFORE anything is sent to a platform.
-- An attempt that never finished, or finished unclear, stops that post from being sent again until the owner says
-- it isn't on the platform. Attempts can't be removed, and an outcome can be recorded only once.

create table public.publish_attempts (
  id bigint generated always as identity primary key,
  scheduled_post_id uuid not null references public.scheduled_posts(id) on delete restrict,
  social_account_id uuid not null references public.social_accounts(id) on delete restrict,
  content_sha256 text not null,
  started_at timestamptz not null default now(),
  finished_at timestamptz,
  outcome text check (outcome in ('published', 'not_sent', 'ambiguous', 'blocked_duplicate')),
  detail text,
  cleared_at timestamptz,
  cleared_by text
);
create unique index publish_attempts_one_open on public.publish_attempts (scheduled_post_id) where outcome is null;
create index publish_attempts_post_idx on public.publish_attempts (scheduled_post_id, id desc);
alter table public.publish_attempts enable row level security;
create policy owner_read on public.publish_attempts for select to authenticated using (public.is_owner());

create or replace function public.publish_attempts_guard()
returns trigger
language plpgsql
as $$
begin
  if tg_op = 'DELETE' then
    raise exception 'publish attempts are permanent';
  end if;
  if new.scheduled_post_id <> old.scheduled_post_id or new.social_account_id <> old.social_account_id
     or new.content_sha256 <> old.content_sha256 or new.started_at <> old.started_at then
    raise exception 'a publish attempt can''t be rewritten';
  end if;
  if old.outcome is not null and new.outcome is distinct from old.outcome then
    raise exception 'this attempt''s outcome is already recorded';
  end if;
  if old.cleared_at is not null and (new.cleared_at is distinct from old.cleared_at or new.cleared_by is distinct from old.cleared_by) then
    raise exception 'this attempt was already cleared';
  end if;
  return new;
end;
$$;
create trigger publish_attempts_guard before update or delete on public.publish_attempts
  for each row execute function public.publish_attempts_guard();
create trigger publish_attempts_no_truncate before truncate on public.publish_attempts
  for each statement execute function public.forbid_change();

-- ---------------------------------------------------------------------------------------------------------------
-- 3. Published posts are permanent, and the same video or text never goes to the same account twice.

alter table public.published_posts
  add column social_account_id uuid references public.social_accounts(id) on delete restrict,
  add column content_sha256 text;
update public.published_posts pp set social_account_id = sp.social_account_id
  from public.scheduled_posts sp where sp.id = pp.scheduled_post_id;
create unique index published_posts_no_duplicate on public.published_posts (social_account_id, content_sha256)
  where content_sha256 is not null;

alter table public.published_posts drop constraint published_posts_scheduled_post_id_fkey,
  add constraint published_posts_scheduled_post_id_fkey foreign key (scheduled_post_id)
      references public.scheduled_posts(id) on delete restrict;

create or replace function public.published_posts_guard()
returns trigger
language plpgsql
as $$
begin
  if tg_op = 'DELETE' then
    raise exception 'published posts are permanent';
  end if;
  if new.scheduled_post_id <> old.scheduled_post_id or new.platform <> old.platform or new.method <> old.method
     or new.published_at <> old.published_at
     or new.social_account_id is distinct from old.social_account_id
     or new.content_sha256 is distinct from old.content_sha256
     or (old.platform_post_id is not null and new.platform_post_id is distinct from old.platform_post_id) then
    raise exception 'a published post''s record can''t be rewritten (only its link, visibility and check time can be filled in)';
  end if;
  return new;
end;
$$;
create or replace function public.published_posts_fill()
returns trigger
language plpgsql
as $$
begin
  if new.social_account_id is null then
    select social_account_id into new.social_account_id from public.scheduled_posts where id = new.scheduled_post_id;
  end if;
  return new;
end;
$$;
create trigger published_posts_fill before insert on public.published_posts
  for each row execute function public.published_posts_fill();
alter table public.published_posts alter column social_account_id set not null;

create trigger published_posts_guard before update or delete on public.published_posts
  for each row execute function public.published_posts_guard();
create trigger published_posts_no_truncate before truncate on public.published_posts
  for each statement execute function public.forbid_change();

-- One live post per variant, and a published post never goes back to waiting.
create unique index scheduled_posts_one_live_per_variant on public.scheduled_posts (variant_id)
  where status <> 'cancelled';

create or replace function public.scheduled_posts_guard()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
begin
  if old.status = 'published' and new.status <> 'published' then
    raise exception 'this post is already published';
  end if;
  if new.variant_id <> old.variant_id or new.social_account_id <> old.social_account_id then
    raise exception 'a post can''t be moved to another account or package';
  end if;
  -- the owner retrying a post that needed checking: their decision clears the unclear attempt, on the record
  if old.status in ('needs_review', 'failed') and new.status = 'scheduled' then
    update public.publish_attempts
       set cleared_at = now(), cleared_by = public.audit_actor(),
           outcome = coalesce(outcome, 'not_sent'), finished_at = coalesce(finished_at, now()),
           detail = coalesce(detail, 'cleared when the post was retried')
     where scheduled_post_id = new.id and cleared_at is null and (outcome is null or outcome = 'ambiguous');
  end if;
  return new;
end;
$$;
create trigger scheduled_posts_guard before update on public.scheduled_posts
  for each row execute function public.scheduled_posts_guard();
