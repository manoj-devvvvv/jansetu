-- ============================================================
-- 018: ML Metadata + Notification Lifecycle — minor gaps
-- Fixes critique #30, #32, #37, #38.
-- Depends on: 000, 004, 005, 009, 011
-- ============================================================

-- ---------- #30: XGBoost model version, matching the pattern already used for BGE-M3 ----------
alter table worker_completion_features
  add column model_version text not null default 'xgboost-v1';


-- ---------- #32: worker_id must agree with worker_assignments.worker_id for the same assignment ----------
-- anomaly_flags and photo_hash_registry each carry their own worker_id FK
-- alongside worker_assignment_id; nothing previously stopped those two from
-- describing different workers. One shared check, reused on both tables.
create or replace function validate_worker_matches_assignment()
returns trigger
language plpgsql
as $$
declare
  actual_worker_id uuid;
begin
  select worker_id into actual_worker_id
    from worker_assignments where id = new.worker_assignment_id;

  if actual_worker_id is distinct from new.worker_id then
    raise exception 'worker_id % does not match worker_assignments.worker_id % for assignment %',
      new.worker_id, actual_worker_id, new.worker_assignment_id;
  end if;

  return new;
end;
$$;

create trigger trg_anomaly_flags_validate_worker
  before insert or update of worker_id, worker_assignment_id on anomaly_flags
  for each row execute function validate_worker_matches_assignment();

create trigger trg_photo_hash_registry_validate_worker
  before insert or update of worker_id, worker_assignment_id on photo_hash_registry
  for each row execute function validate_worker_matches_assignment();


-- ---------- #37: push subscription lifecycle ----------
alter table push_subscriptions add column is_active boolean not null default true;
alter table push_subscriptions add column invalidated_at timestamptz;

create index idx_push_subscriptions_active on push_subscriptions (is_active) where is_active = true;

-- ---------- #38: notification delivery failure detail ----------
alter table notification_log add column failure_reason text;
