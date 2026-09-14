-- ============================================================
-- 006: SLA Configuration & Tracking, Worker Excuses,
--      Officer Verification Actions, Escalations
-- Depends on: 000, 002 (officers), 003 (complaints), 005 (worker_assignments)
-- ============================================================

-- ---------- SLA configuration (one row per tracker type) ----------
create table sla_configs (
  tracker_type   sla_tracker_type primary key,
  duration_hours integer not null check (duration_hours > 0),
  description    text,
  updated_at     timestamptz not null default now()
);

create trigger trg_sla_configs_updated_at
  before update on sla_configs
  for each row execute function set_updated_at();

-- Only the worker SLA duration is explicitly given in the product spec (36h).
-- Panchayat/mandal/district verification SLAs are NOT specified in the source
-- requirements — insert them with your organization's agreed values before
-- relying on auto-escalation for those levels, e.g.:
--   insert into sla_configs values ('panchayat_verification', 48, 'Panchayat review window', now());
--   insert into sla_configs values ('mandal_verification',    72, 'Mandal review window', now());
--   insert into sla_configs values ('district_verification',  96, 'District review window', now());
insert into sla_configs (tracker_type, duration_hours, description)
values ('worker_assignment', 36, 'Time given to a worker to resolve a job before auto-escalation');


-- ---------- SLA trackers (one active timer per worker_assignment, or per complaint+level) ----------
create table sla_trackers (
  id                   uuid primary key default gen_random_uuid(),
  tracker_type         sla_tracker_type not null,
  worker_assignment_id uuid references worker_assignments(id) on delete cascade,
  complaint_id         uuid references complaints(id) on delete cascade,
  started_at           timestamptz not null default now(),
  due_at               timestamptz not null,
  breached             boolean not null default false,
  breach_processed_at  timestamptz,
  resolved_at          timestamptz,
  created_at           timestamptz not null default now(),

  constraint chk_sla_tracker_reference check (
    (tracker_type = 'worker_assignment'
       and worker_assignment_id is not null and complaint_id is null)
    or
    (tracker_type in ('panchayat_verification','mandal_verification','district_verification')
       and complaint_id is not null and worker_assignment_id is null)
  )
);

-- Only one *active* (unresolved) timer per assignment, and per (complaint, level).
create unique index uq_sla_tracker_assignment_active
  on sla_trackers (worker_assignment_id)
  where worker_assignment_id is not null and resolved_at is null;

create unique index uq_sla_tracker_complaint_active
  on sla_trackers (complaint_id, tracker_type)
  where complaint_id is not null and resolved_at is null;

create index idx_sla_trackers_due_unresolved on sla_trackers (due_at) where resolved_at is null;


-- ---------- Worker excuse (max 1 per assignment, 24h extension) ----------
create table worker_excuses (
  id                   uuid primary key default gen_random_uuid(),
  worker_assignment_id uuid not null unique references worker_assignments(id) on delete cascade,
  reason_text          text,
  reason_audio_url     text,
  extension_hours      smallint not null default 24 check (extension_hours > 0),
  requested_at         timestamptz not null default now(),

  constraint chk_worker_excuse_reason check (reason_text is not null or reason_audio_url is not null)
);

-- Applying an excuse: mark the assignment, extend its SLA tracker's due_at.
create or replace function apply_worker_excuse()
returns trigger
language plpgsql
as $$
begin
  update worker_assignments
     set status = 'worker_excused', excuse_used = true, updated_at = now()
   where id = new.worker_assignment_id;

  update sla_trackers
     set due_at = due_at + make_interval(hours => new.extension_hours)
   where worker_assignment_id = new.worker_assignment_id
     and resolved_at is null;

  return new;
end;
$$;

create trigger trg_worker_excuses_apply
  after insert on worker_excuses
  for each row execute function apply_worker_excuse();


-- ---------- Officer verification actions (verify / dismiss / wait / escalate) ----------
-- Same table serves panchayat, mandal and district officers (verify_service.py is shared).
create table complaint_verification_actions (
  id           uuid primary key default gen_random_uuid(),
  complaint_id uuid not null references complaints(id) on delete cascade,
  officer_id   uuid not null references officers(id) on delete restrict,
  action_type  verification_action_type not null,
  reason       text,
  created_at   timestamptz not null default now(),

  constraint chk_verification_reason_required
    check (action_type = 'verify' or (reason is not null and length(trim(reason)) > 0))
);

create index idx_verification_actions_complaint on complaint_verification_actions (complaint_id);
create index idx_verification_actions_officer on complaint_verification_actions (officer_id);

-- Enforce max 2 "wait" actions per complaint. Reads complaints.wait_count (the
-- single authoritative counter, maintained by trg_verification_actions_apply
-- below) with FOR UPDATE so two concurrent "wait" clicks on the same complaint
-- serialize correctly instead of both reading a stale count.
create or replace function enforce_max_wait_actions()
returns trigger
language plpgsql
as $$
declare
  current_count smallint;
begin
  if new.action_type = 'wait' then
    select wait_count into current_count from complaints where id = new.complaint_id for update;

    if current_count >= 2 then
      raise exception 'Complaint % already has the maximum of 2 "wait" actions', new.complaint_id;
    end if;
  end if;
  return new;
end;
$$;

create trigger trg_verification_actions_max_wait
  before insert on complaint_verification_actions
  for each row execute function enforce_max_wait_actions();

-- Apply the simple state transitions automatically. "verify" is intentionally
-- excluded — it requires the worker-matching algorithm (assign_worker.py) to pick
-- a suitable worker and create the worker_assignments + sla_trackers rows in one
-- transaction, which is application logic, not something a trigger should do.
create or replace function apply_verification_action_to_complaint()
returns trigger
language plpgsql
as $$
begin
  if new.action_type = 'dismiss' then
    update complaints set status = 'dismissed', updated_at = now() where id = new.complaint_id;
  elsif new.action_type = 'wait' then
    update complaints set status = 'waiting', wait_count = wait_count + 1, updated_at = now()
     where id = new.complaint_id;
  end if;
  -- 'escalate' is applied by trg_escalations_apply once the escalations row exists.
  return new;
end;
$$;

create trigger trg_verification_actions_apply
  after insert on complaint_verification_actions
  for each row execute function apply_verification_action_to_complaint();


-- ---------- Escalations ----------
create table escalations (
  id             uuid primary key default gen_random_uuid(),
  complaint_id   uuid not null references complaints(id) on delete cascade,
  from_level     jurisdiction_level not null,
  to_level       jurisdiction_level not null,
  trigger_type   escalation_trigger_type not null,
  escalated_by   uuid references officers(id) on delete set null,  -- null when system/SLA-triggered
  reason         text not null,
  sla_tracker_id uuid references sla_trackers(id) on delete set null,
  created_at     timestamptz not null default now(),
  resolved_at    timestamptz,
  resolved_by    uuid references officers(id) on delete set null,

  constraint chk_escalation_direction check (
    (from_level = 'panchayat' and to_level = 'mandal') or
    (from_level = 'mandal' and to_level = 'district')
  ),
  constraint chk_escalation_manual_has_officer
    check (trigger_type <> 'manual' or escalated_by is not null)
);

create index idx_escalations_complaint on escalations (complaint_id);
create index idx_escalations_unresolved on escalations (to_level) where resolved_at is null;

-- Move the complaint into the new level's queue automatically.
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
  return new;
end;
$$;

create trigger trg_escalations_apply
  after insert on escalations
  for each row execute function apply_escalation_to_complaint();
