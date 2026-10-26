-- v3.1: a model that stops working for a lasting reason pauses itself and is re-tested on a schedule;
-- it comes back by itself when it works again. `enabled` stays the owner's own on/off switch.

alter table public.ai_model_configs
  add column pause_reason text check (pause_reason in ('retired', 'payment')),
  add column paused_at timestamptz,
  add column next_check_at timestamptz,
  add column checks int not null default 0,
  add column pause_detail text;

create index ai_model_configs_due_idx on public.ai_model_configs (next_check_at) where pause_reason is not null;

-- Kimi K3 on Bluesminds was switched off by hand when it reached its end of life: hand it to the schedule instead.
update public.ai_model_configs
   set enabled = true, pause_reason = 'retired', paused_at = now(), next_check_at = now() + interval '7 days',
       pause_detail = 'The provider says this model reached its end of life on 2026-10-15'
 where provider like 'bluesminds%' and model = 'moonshotai/kimi-k3' and not enabled;
