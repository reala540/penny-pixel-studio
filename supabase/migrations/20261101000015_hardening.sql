-- v3.4 hardening from the Supabase security advisor (26 Oct 2026). No behaviour change.
-- 1. Trigger functions are never meant to be called directly: nobody on the API may execute them
--    (triggers keep firing: PostgreSQL doesn't check EXECUTE when a trigger runs).
-- 2. Helper functions get a fixed search_path.
do $$
declare f record;
begin
  for f in select p.oid::regprocedure sig from pg_proc p join pg_namespace n on n.oid = p.pronamespace
            where n.nspname = 'public' and p.prorettype = 'trigger'::regtype loop
    execute format('revoke execute on function %s from public, anon, authenticated', f.sig);
  end loop;
end $$;

do $$
declare f record;
begin
  for f in select p.oid::regprocedure sig from pg_proc p join pg_namespace n on n.oid = p.pronamespace
            where n.nspname = 'public' and p.proname in ('audit_actor', 'audit_row_digest', 'forbid_change',
                  'publish_attempts_guard', 'published_posts_guard', 'published_posts_fill') loop
    execute format('alter function %s set search_path = public', f.sig);
  end loop;
end $$;
