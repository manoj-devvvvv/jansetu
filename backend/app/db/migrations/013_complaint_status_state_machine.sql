-- ============================================================
-- 013: Complaint Status State Machine + Unified Timeline
-- Fixes critique #8 (Critical) and #40 (High).
-- Depends on: 000, 003
-- ============================================================

-- ---------- Explicit transition matrix ----------
-- Data-driven on purpose: adjusting the workflow later is an INSERT/DELETE here,
-- not a code deploy. Self-transitions (new.status = old.status) are always
-- allowed and are handled in the trigger function, not listed here.
create table complaint_status_transitions (
  from_status complaint_status not null,
  to_status   complaint_status not null,
  primary key (from_status, to_status)
);

insert into complaint_status_transitions (from_status, to_status) values
  ('submitted', 'waiting'),
  ('submitted', 'escalated'),
  ('submitted', 'dismissed'),
  ('submitted', 'assigned'),
  ('waiting', 'escalated'),
  ('waiting', 'dismissed'),
  ('waiting', 'assigned'),
  ('escalated', 'waiting'),
  ('escalated', 'dismissed'),
  ('escalated', 'assigned'),
  ('assigned', 'in_progress'),
  ('assigned', 'escalated'),
  ('in_progress', 'pending_citizen_confirmation'),
  ('in_progress', 'escalated'),
  ('pending_citizen_confirmation', 'closed'),
  ('pending_citizen_confirmation', 'reopened'),
  ('reopened', 'assigned'),
  ('reopened', 'escalated');
-- 'closed' and 'dismissed' are terminal: no rows with them as from_status.

create or replace function enforce_complaint_status_transition()
returns trigger
language plpgsql
as $$
begin
  if new.status = old.status then
    return new; -- no-op update (e.g. a second "wait" while already waiting) is always fine
  end if;

  if not exists (
    select 1 from complaint_status_transitions
     where from_status = old.status and to_status = new.status
  ) then
    raise exception 'Invalid complaint status transition: % -> %', old.status, new.status;
  end if;

  return new;
end;
$$;

create trigger trg_complaints_enforce_status_transition
  before update of status on complaints
  for each row execute function enforce_complaint_status_transition();


-- ---------- Unified timeline (auto-populated, no app-layer bookkeeping needed) ----------
-- Answers "when did this complaint's status change and to what" in one place.
-- Who/why for a given change is cross-referenced from complaint_verification_actions,
-- escalations, worker_assignments or closure_verifications by complaint_id + timestamp
-- proximity — this table intentionally does not carry a polymorphic "caused_by" FK.
create table complaint_status_history (
  id           uuid primary key default gen_random_uuid(),
  complaint_id uuid not null references complaints(id) on delete cascade,
  old_status   complaint_status,   -- null on the row created at complaint insert
  new_status   complaint_status not null,
  changed_at   timestamptz not null default now()
);

create index idx_complaint_status_history_complaint on complaint_status_history (complaint_id, changed_at);

create or replace function log_complaint_status_change()
returns trigger
language plpgsql
as $$
begin
  if tg_op = 'INSERT' then
    insert into complaint_status_history (complaint_id, old_status, new_status)
    values (new.id, null, new.status);
  elsif tg_op = 'UPDATE' and new.status is distinct from old.status then
    insert into complaint_status_history (complaint_id, old_status, new_status)
    values (new.id, old.status, new.status);
  end if;
  return new;
end;
$$;

-- AFTER, so it only fires once trg_complaints_enforce_status_transition has approved the change.
create trigger trg_complaints_status_history
  after insert or update of status on complaints
  for each row execute function log_complaint_status_change();

-- Backfill: the trigger only sees changes from this point forward. Give any
-- complaint that already existed a starting history row too. Idempotent —
-- safe to re-run, and a no-op on a table with no prior rows.
insert into complaint_status_history (complaint_id, old_status, new_status, changed_at)
select c.id, null, c.status, c.created_at
  from complaints c
 where not exists (
   select 1 from complaint_status_history h where h.complaint_id = c.id
 );

-- ---------- RLS for the two new tables (same lockdown policy as 012) ----------
alter table complaint_status_transitions enable row level security;
alter table complaint_status_transitions force row level security;
alter table complaint_status_history enable row level security;
alter table complaint_status_history force row level security;
