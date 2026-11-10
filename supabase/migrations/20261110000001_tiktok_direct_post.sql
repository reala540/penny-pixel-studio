-- TikTok Direct Post: the owner's per-post choices from the dashboard's TikTok posting screen (who can watch,
-- comments/Duet/Stitch, commercial-content disclosure, consent time). Written only by the Worker after it re-checks
-- them against the creator's live TikTok settings; the engine posts directly only when this is filled in.
alter table public.scheduled_posts add column if not exists tiktok_post jsonb;
comment on column public.scheduled_posts.tiktok_post is
  'TikTok Direct Post settings confirmed by the owner: {privacy_level, allow_comment, allow_duet, allow_stitch, disclose, your_brand, branded_content, confirmed_at, creator_username, creator_nickname}';
