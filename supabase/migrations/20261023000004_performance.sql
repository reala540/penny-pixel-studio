-- Indexes for the joins the dashboard and engine run constantly (Supabase performance advisor).
create index if not exists content_variants_project_idx on public.content_variants (project_id);
create index if not exists content_variants_account_idx on public.content_variants (social_account_id);
create index if not exists scheduled_posts_variant_idx on public.scheduled_posts (variant_id);
create index if not exists scheduled_posts_account_idx on public.scheduled_posts (social_account_id, scheduled_at);
create index if not exists content_projects_parent_idx on public.content_projects (parent_project_id);
create index if not exists content_projects_script_idx on public.content_projects (current_script_version_id);
create index if not exists media_assets_project_idx on public.media_assets (project_id, kind);
create index if not exists thumbnails_project_idx on public.thumbnails (project_id);
create index if not exists research_claims_version_idx on public.research_claims (script_version_id);
create index if not exists job_attempts_job_idx on public.job_attempts (job_id);
create index if not exists manual_tasks_post_idx on public.manual_tasks (scheduled_post_id);

-- Evaluate auth.uid() once per statement instead of once per row (ALTER keeps the policy in place).
alter policy owner_select_self on public.app_owner using (user_id = (select auth.uid()));
alter policy owner_insert on public.approvals with check (public.is_owner() and decided_by = (select auth.uid()));
