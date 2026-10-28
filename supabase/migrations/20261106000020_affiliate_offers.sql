-- Affiliate offers the owner adds by hand. Off until an offer exists and is switched on. A matching offer is added
-- to a video's description with a clear disclosure first; it's never put in X posts, Shorts or the narration.

create table if not exists public.affiliate_offers (
  id uuid primary key default gen_random_uuid(),
  name text not null check (length(name) between 2 and 80),
  url text not null check (url ~ '^https://[^\s]+$' and length(url) <= 500),
  channel_slug text not null default 'both' check (channel_slug in ('ai', 'money', 'both')),
  topics text[] not null default '{}' check (cardinality(topics) between 1 and 20),
  blurb text check (blurb is null or length(blurb) <= 200),
  disclosure text not null default 'Affiliate link: I may earn a small commission if you sign up, at no extra cost to you.'
    check (length(disclosure) between 20 and 300),
  enabled boolean not null default true,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

alter table public.affiliate_offers enable row level security;
drop policy if exists owner_select on public.affiliate_offers;
drop policy if exists owner_insert on public.affiliate_offers;
drop policy if exists owner_update on public.affiliate_offers;
drop policy if exists owner_delete on public.affiliate_offers;
create policy owner_select on public.affiliate_offers for select to authenticated using (public.is_owner());
create policy owner_insert on public.affiliate_offers for insert to authenticated with check (public.is_owner());
create policy owner_update on public.affiliate_offers for update to authenticated using (public.is_owner()) with check (public.is_owner());
create policy owner_delete on public.affiliate_offers for delete to authenticated using (public.is_owner());
revoke all on public.affiliate_offers from anon;
revoke truncate, trigger, references on public.affiliate_offers from authenticated;
grant select, insert, update, delete on public.affiliate_offers to authenticated;

notify pgrst, 'reload schema';
