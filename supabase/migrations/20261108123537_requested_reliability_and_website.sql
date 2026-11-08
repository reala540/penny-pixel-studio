-- Independent, automatically reviewed article snapshots. URLs survive title changes.
create table if not exists public.website_articles (
  project_id uuid primary key references public.content_projects(id),
  script_version_id uuid not null references public.script_versions(id),
  slug text not null unique,
  title text not null,
  blocks jsonb not null,
  review jsonb not null,
  published_at timestamptz not null default now(),
  modified_at timestamptz not null default now(),
  checked_at timestamptz not null default now()
);
alter table public.website_articles enable row level security;
grant select on public.website_articles to authenticated;
create policy owner_read on public.website_articles for select to authenticated using ((select public.is_owner()));
-- Secret tables deliberately remain inaccessible to normal clients.
alter policy owner_draft_read on public.studio_drafts using ((select public.is_owner()) and owner_id=(select auth.uid()));

create or replace function public.require_manual_post_url() returns trigger language plpgsql set search_path=public as $$
begin
  if new.method='manual' and (new.url is null or new.url !~ '^https://[^/[:space:]]+/[^[:space:]]+') then
    raise exception 'Paste the public post URL before marking it done';
  end if;
  return new;
end $$;
create trigger manual_post_url before insert or update on public.published_posts
for each row execute function public.require_manual_post_url();
notify pgrst, 'reload schema';

create table public.model_output_checks (
 id bigint generated always as identity primary key,
 provider text not null, model text not null, role text not null,
 valid_output boolean not null, created_at timestamptz not null default now()
);
create index model_output_checks_recent on public.model_output_checks(provider,model,created_at desc);
alter table public.model_output_checks enable row level security;
grant select on public.model_output_checks to authenticated;
create policy owner_read on public.model_output_checks for select to authenticated using ((select public.is_owner()));

revoke all on function public.require_manual_post_url() from public,anon,authenticated;

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
  if p_url is null or p_url !~ '^https://[^/[:space:]]+/[^[:space:]]+' then
    raise exception 'Paste the public post URL before marking it done';
  end if;
  update public.manual_tasks set status = 'done', done_at = now()
   where id = p_task_id and status = 'open'
  returning scheduled_post_id, platform into v_post, v_platform;
  if v_post is null then
    return;
  end if;
  insert into public.published_posts (scheduled_post_id, platform, url, visibility, method)
  values (v_post, v_platform, nullif(p_url, ''), 'public', 'manual')
  on conflict (scheduled_post_id) do update set url = excluded.url, visibility='public';
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


update public.channel_profiles set topic_focus='Practical AI workflows for freelancers and small businesses: beginner guides, tutorials, comparisons and troubleshooting',
 audience_profile=jsonb_set(audience_profile,'{who}','"Freelancers and small-business owners who want practical AI workflows without the hype"')
 where slug='ai';

revoke all on public.website_articles,public.model_output_checks from public,anon,authenticated;
grant select on public.website_articles,public.model_output_checks to authenticated;
