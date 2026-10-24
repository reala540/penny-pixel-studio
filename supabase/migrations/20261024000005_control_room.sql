-- Control Room reads recent model activity and joins it to the owning job.
-- Existing owner-select RLS on both tables remains the only client access path.
create index if not exists provider_usage_created_idx
  on public.provider_usage (created_at desc);
create index if not exists provider_usage_job_created_idx
  on public.provider_usage (job_id, created_at desc);
create index if not exists generation_jobs_updated_idx
  on public.generation_jobs (updated_at desc);
