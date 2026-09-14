-- ============================================================
-- 014: Assignment Active-State + SLA Lifecycle Corrections
-- Fixes critique #14 (High), #18, #19 (Critical), #22, #23 (Critical).
-- Depends on: 000, 005, 006, 007
-- ============================================================

-- ---------- 1. Explicit "current active assignment" ----------
alter table worker_assignments add column is_active boolean not null default true;

-- Defensive backfill: if this ever runs against a table that already has
-- rows (e.g. a test dataset), make sure only the most recent, non-terminal
-- assignment per complaint stays active before the unique index below is
-- created — otherwise two "active by default" rows for the same complaint
-- would collide against it. On a freshly-created (empty) table this is a
-- no-op.
update worker_assignments wa
   set is_active = false
 where wa.status in ('completed', 'rejected')
    or wa.id <> (
      select wa2.id from worker_assignments wa2
       where wa2.complaint_id = wa.complaint_id
       order by wa2.assigned_at desc, wa2.id desc
       limit 1
    );

-- At most one active attempt per complaint at a time. Reassignment after a
-- rejection or a reopened complaint creates a NEW worker_assignments row once
-- the old one has flipped is_active = false (see trigger below), so this does
-- not conflict with a complaint legitimately having several rows over time.
create unique index uq_worker_assignments_active
  on worker_assignments (complaint_id)
  where is_active = true;

create or replace function set_worker_assignment_active_flag()
returns trigger
language plpgsql
as $$
begin
  if new.status in ('completed', 'rejected') then
    new.is_active := false;
  end if;
  return new;
end;
$$;

create trigger trg_worker_assignments_active_flag
  before update of status on worker_assignments
  for each row execute function set_worker_assignment_active_flag();


-- ---------- 2. Side effects that must never be forgotten ----------
-- accepted   -> complaint becomes 'in_progress'
-- completed  -> resolve this assignment's SLA tracker, move complaint to
--               'pending_citizen_confirmation', open its closure_verification
-- rejected   -> resolve this assignment's SLA tracker (this attempt is over;
--               reassignment is a fresh worker_assignments row with its own timer)
-- Each UPDATE below is guarded by the expected prior complaint status so a
-- stale/duplicate fire is a safe no-op instead of a forced invalid transition.
create or replace function apply_worker_assignment_side_effects()
returns trigger
language plpgsql
as $$
begin
  if new.status = old.status then
    return new;
  end if;

  if new.status = 'accepted' then
    update complaints set status = 'in_progress', updated_at = now()
     where id = new.complaint_id and status = 'assigned';

  elsif new.status = 'completed' then
    update sla_trackers set resolved_at = now()
     where worker_assignment_id = new.id and resolved_at is null;

    update complaints set status = 'pending_citizen_confirmation', updated_at = now()
     where id = new.complaint_id and status = 'in_progress';

    insert into closure_verifications (complaint_id, worker_assignment_id)
    values (new.complaint_id, new.id);

  elsif new.status = 'rejected' then
    update sla_trackers set resolved_at = now()
     where worker_assignment_id = new.id and resolved_at is null;
  end if;

  return new;
end;
$$;

create trigger trg_worker_assignments_side_effects
  after update of status on worker_assignments
  for each row execute function apply_worker_assignment_side_effects();


-- ---------- 3. Worker excuse: validate eligibility before accepting it ----------
-- The UNIQUE(worker_assignment_id) constraint already blocks a *second* excuse;
-- this adds the missing check that the *first* one is even valid to request.
create or replace function validate_worker_excuse_eligibility()
returns trigger
language plpgsql
as $$
declare
  current_status assignment_status;
begin
  select status into current_status
    from worker_assignments
   where id = new.worker_assignment_id
     for update;

  if current_status is null then
    raise exception 'worker_assignment_id % does not exist', new.worker_assignment_id;
  end if;

  if current_status not in ('assigned', 'accepted', 'in_progress') then
    raise exception 'Cannot request an excuse for a worker assignment in status %', current_status;
  end if;

  return new;
end;
$$;

create trigger trg_worker_excuses_validate_eligibility
  before insert on worker_excuses
  for each row execute function validate_worker_excuse_eligibility();


-- ---------- 4. Escalation lifecycle: resolve the old SLA, open the new one, no duplicates ----------

-- No two concurrently-open escalations to the same level for the same complaint.
create unique index uq_escalations_no_duplicate_open
  on escalations (complaint_id, to_level)
  where resolved_at is null;

-- Replaces the version from 006: additionally resolves the level being escalated
-- FROM, and opens a tracker for the level being escalated TO if (and only if)
-- an sla_config row exists for it — panchayat/mandal/district durations are
-- organization-defined and may not be seeded yet (see 006's comment).
create or replace function apply_escalation_to_complaint()
returns trigger
language plpgsql
as $$
begin
  update complaints
     set current_review_level = new.to_level,
         status = 'escalated',
         updated_at = now()
   where id = new.complaint_id;

  update sla_trackers
     set resolved_at = now()
   where complaint_id = new.complaint_id
     and tracker_type = (new.from_level::text || '_verification')::sla_tracker_type
     and resolved_at is null;

  insert into sla_trackers (tracker_type, complaint_id, started_at, due_at)
  select (new.to_level::text || '_verification')::sla_tracker_type,
         new.complaint_id,
         now(),
         now() + make_interval(hours => sc.duration_hours)
    from sla_configs sc
   where sc.tracker_type = (new.to_level::text || '_verification')::sla_tracker_type
  -- Predicate must textually match uq_sla_tracker_complaint_active from 006
  -- exactly, or Postgres cannot infer it as the arbiter index.
  on conflict (complaint_id, tracker_type) where complaint_id is not null and resolved_at is null
  do nothing;

  return new;
end;
$$;
-- trigger trg_escalations_apply from 006 already points at this function name,
-- so CREATE OR REPLACE above is all that's needed — no need to touch the trigger.

-- Replaces the version from 006: additionally resolves any open escalation
-- record for this complaint at the acting officer's level when they dismiss/wait,
-- so a resolved verification action can't leave a stale "still escalated" row
-- that would otherwise block a legitimate future re-escalation to that level.
create or replace function apply_verification_action_to_complaint()
returns trigger
language plpgsql
as $$
declare
  acting_officer_level jurisdiction_level;
begin
  if new.action_type = 'dismiss' then
    update complaints set status = 'dismissed', updated_at = now() where id = new.complaint_id;
  elsif new.action_type = 'wait' then
    update complaints set status = 'waiting', wait_count = wait_count + 1, updated_at = now()
     where id = new.complaint_id;
  end if;

  if new.action_type in ('dismiss', 'wait') then
    select level into acting_officer_level from officers where id = new.officer_id;

    update escalations
       set resolved_at = now(), resolved_by = new.officer_id
     where complaint_id = new.complaint_id
       and to_level = acting_officer_level
       and resolved_at is null;
  end if;
  -- 'escalate' is applied by trg_escalations_apply once the escalations row exists.
  return new;
end;
$$;
