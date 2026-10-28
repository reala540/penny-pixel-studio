-- Performance page: numbers read from the platforms (read-only), and what each package cost to make.
-- Nothing here posts, approves or spends anything. A number a platform didn't give is listed in `missing`, so the
-- page can say "not available" instead of showing zero.

-- render minutes and AI calls are linked to the package they were for
alter table public.provider_usage add column if not exists project_id uuid references public.content_projects(id) on delete set null;
create index if not exists provider_usage_project on public.provider_usage (project_id) where project_id is not null;

create table if not exists public.post_metrics (
  id uuid primary key default gen_random_uuid(),
  published_post_id uuid not null references public.published_posts(id) on delete cascade,
  collected_on date not null,
  views bigint,
  watch_minutes numeric,
  avg_view_seconds numeric,
  impressions bigint,
  ctr numeric,                       -- click-through rate, 0-100
  likes bigint,
  comments bigint,
  shares bigint,
  subscribers_gained bigint,
  revenue_usd numeric,
  missing text[] not null default '{}',
  source text not null,
  created_at timestamptz not null default now(),
  unique (published_post_id, collected_on)
);

create table if not exists public.account_metrics (
  id uuid primary key default gen_random_uuid(),
  social_account_id uuid not null references public.social_accounts(id) on delete cascade,
  collected_on date not null,
  period_days int not null,
  views bigint,
  watch_minutes numeric,
  subscribers_gained bigint,
  top_countries jsonb not null default '[]',
  missing text[] not null default '{}',
  note text,
  source text not null,
  created_at timestamptz not null default now(),
  unique (social_account_id, collected_on)
);

alter table public.post_metrics enable row level security;
alter table public.account_metrics enable row level security;
drop policy if exists owner_select on public.post_metrics;
drop policy if exists owner_select on public.account_metrics;
create policy owner_select on public.post_metrics for select to authenticated using (public.is_owner());
create policy owner_select on public.account_metrics for select to authenticated using (public.is_owner());
revoke all on public.post_metrics, public.account_metrics from anon;
revoke insert, update, delete, truncate, trigger, references on public.post_metrics, public.account_metrics from authenticated;
grant select on public.post_metrics, public.account_metrics to authenticated;

-- One row per published post: where it went, its package, and its latest numbers.
create or replace function public.studio_performance(p_days integer default 90)
returns table(published_post_id uuid, platform text, account_label text, kind text, channel_slug text, project_id uuid,
              title text, url text, published_at timestamptz, collected_on date, views bigint, watch_minutes numeric,
              avg_view_seconds numeric, impressions bigint, ctr numeric, likes bigint, comments bigint, shares bigint,
              subscribers_gained bigint, revenue_usd numeric, missing text[])
language plpgsql security definer set search_path = public stable as $$
begin
  if not public.is_owner() then raise exception 'owner only'; end if;
  return query
  select pp.id, pp.platform, a.label, v.kind, p.channel_slug, coalesce(p.parent_project_id, p.id),
         coalesce(v.title, p.title), pp.url, pp.published_at, m.collected_on, m.views, m.watch_minutes,
         m.avg_view_seconds, m.impressions, m.ctr, m.likes, m.comments, m.shares, m.subscribers_gained,
         m.revenue_usd, m.missing
    from published_posts pp
    join scheduled_posts sp on sp.id = pp.scheduled_post_id
    join content_variants v on v.id = sp.variant_id
    join content_projects p on p.id = v.project_id
    join social_accounts a on a.id = sp.social_account_id
    left join lateral (select * from post_metrics x where x.published_post_id = pp.id
                        order by x.collected_on desc limit 1) m on true
   where pp.published_at > now() - make_interval(days => greatest(least(p_days, 730), 1))
   order by pp.published_at desc;
end $$;
revoke all on function public.studio_performance(integer) from public, anon;
grant execute on function public.studio_performance(integer) to authenticated;

-- What each package (main video plus its Shorts) cost: AI calls and their cost, render minutes, X spend.
create or replace function public.studio_package_costs(p_days integer default 90)
returns table(project_id uuid, title text, channel_slug text, created_at timestamptz, ai_calls bigint, ai_cost_usd numeric,
              render_minutes numeric, x_spend_usd numeric)
language plpgsql security definer set search_path = public stable as $$
begin
  if not public.is_owner() then raise exception 'owner only'; end if;
  return query
  with fam as (
    select h.id head, f.id member from content_projects h
      join content_projects f on f.id = h.id or f.parent_project_id = h.id
     where h.parent_project_id is null and h.created_at > now() - make_interval(days => greatest(least(p_days, 730), 1))
  ), use as (
    select f.head, u.* from fam f
      join provider_usage u on u.project_id = f.member
                            or u.job_id in (select j.id from generation_jobs j where j.project_id = f.member)
  ), x as (
    select f.head, sum(r.amount_usd) spend from fam f
      join content_variants v on v.project_id = f.member
      join scheduled_posts sp on sp.variant_id = v.id
      join budget_reservations r on r.reference = 'x:' || sp.idempotency_key and r.status = 'committed'
     group by f.head
  )
  select h.id, h.title, h.channel_slug, h.created_at,
         coalesce((select sum(u.requests) from use u where u.head = h.id and u.service = 'llm'), 0)::bigint,
         coalesce((select sum(u.cost_usd) from use u where u.head = h.id and u.service = 'llm'), 0)::numeric,
         coalesce((select sum(u.latency_ms) / 60000.0 from use u where u.head = h.id and u.service = 'render'), 0)::numeric,
         coalesce((select x.spend from x where x.head = h.id), 0)::numeric
    from content_projects h
   where h.id in (select head from fam)
   order by h.created_at desc;
end $$;
revoke all on function public.studio_package_costs(integer) from public, anon;
grant execute on function public.studio_package_costs(integer) to authenticated;

notify pgrst, 'reload schema';
