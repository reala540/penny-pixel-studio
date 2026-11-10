-- TikTok: an accepted upload remains processing until TikTok confirms its result.
alter table public.scheduled_posts add column tiktok_upload jsonb;
alter table public.scheduled_posts drop constraint scheduled_posts_status_check;
alter table public.scheduled_posts add constraint scheduled_posts_status_check check
  (status in ('pending_approval','scheduled','publishing','processing','published','failed','needs_manual','needs_review','cancelled','blocked'));

-- Identity of the saved caption, render recipe, script and connected creator shown to the owner.
create function public.tiktok_content_snapshot(p_post_id uuid) returns jsonb
language sql stable security invoker set search_path = '' as $$
  select jsonb_build_object('variant_id', v.id, 'account_id', a.id, 'account_external_id', a.external_id,
    'script_version_id', p.current_script_version_id, 'title', coalesce(v.title,''), 'body', coalesce(v.body,''),
    'hashtags', coalesce(to_jsonb(v.hashtags),'[]'::jsonb), 'render', p.recipe->'render', 'preview_key', p.recipe->'preview_key')
  from public.scheduled_posts sp join public.content_variants v on v.id=sp.variant_id
  join public.content_projects p on p.id=v.project_id join public.social_accounts a on a.id=sp.social_account_id
  where sp.id=p_post_id and a.platform='tiktok';
$$;
revoke all on function public.tiktok_content_snapshot(uuid) from public, anon, authenticated;
grant execute on function public.tiktok_content_snapshot(uuid) to service_role;

-- Compare the displayed snapshot and save consent in one transaction, even if another tab is editing.
create function public.confirm_tiktok_post(p_post_id uuid, p_settings jsonb, p_expected jsonb) returns jsonb
language plpgsql security invoker set search_path = '' as $$
declare sp public.scheduled_posts; current_snapshot jsonb; saved jsonb;
begin
  select * into sp from public.scheduled_posts where id=p_post_id for update;
  if not found or sp.status in ('published','publishing','processing','cancelled') or sp.tiktok_upload is not null then
    raise exception 'This post cannot be changed while publishing or after it has been sent.';
  end if;
  perform 1 from public.content_variants where id=sp.variant_id for update;
  perform 1 from public.content_projects where id=(select project_id from public.content_variants where id=sp.variant_id) for update;
  perform 1 from public.social_accounts where id=sp.social_account_id for update;
  current_snapshot := public.tiktok_content_snapshot(p_post_id);
  if current_snapshot is null then raise exception 'This is not a TikTok post.'; end if;
  if p_settings is not null then
    if p_expected is null or p_expected is distinct from current_snapshot then
      raise exception 'The video, caption or account changed. Save the post and reopen TikTok settings before confirming.';
    end if;
    if p_settings->>'consent' is distinct from 'true' then raise exception 'TikTok consent is required.'; end if;
    saved := p_settings || jsonb_build_object('content_snapshot', current_snapshot, 'confirmed_at', now());
  end if;
  update public.scheduled_posts set tiktok_post=saved where id=p_post_id;
  return saved;
end;
$$;
revoke all on function public.confirm_tiktok_post(uuid,jsonb,jsonb) from public, anon, authenticated;
grant execute on function public.confirm_tiktok_post(uuid,jsonb,jsonb) to service_role;

-- A caption or recipe cannot change underneath an active TikTok upload.
create function public.tiktok_content_in_flight() returns trigger
language plpgsql security invoker set search_path = '' as $$
begin
  if tg_table_name='content_variants' then
    if (old.title, old.body, old.hashtags, old.project_id) is not distinct from (new.title, new.body, new.hashtags, new.project_id) then return new; end if;
    if exists(select 1 from public.scheduled_posts sp join public.social_accounts a on a.id=sp.social_account_id
      where sp.variant_id=old.id and a.platform='tiktok' and sp.status in ('publishing','processing')) then
      raise exception 'TikTok is uploading this post. Wait for its result before editing.';
    end if;
  else
    if (old.recipe->'render', old.recipe->'preview_key', old.current_script_version_id) is not distinct from
       (new.recipe->'render', new.recipe->'preview_key', new.current_script_version_id) then return new; end if;
    if exists(select 1 from public.scheduled_posts sp join public.content_variants v on v.id=sp.variant_id
      join public.social_accounts a on a.id=sp.social_account_id where v.project_id=old.id and a.platform='tiktok'
      and sp.status in ('publishing','processing')) then
      raise exception 'TikTok is uploading a video from this package. Wait for its result before editing.';
    end if;
  end if;
  return new;
end;
$$;
revoke all on function public.tiktok_content_in_flight() from public, anon, authenticated;
create trigger tiktok_variant_in_flight before update on public.content_variants for each row execute function public.tiktok_content_in_flight();
create trigger tiktok_project_in_flight before update on public.content_projects for each row execute function public.tiktok_content_in_flight();
