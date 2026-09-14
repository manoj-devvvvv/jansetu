-- ============================================================
-- 007: Verifiable Closure — Citizen Accountability Loop
-- Depends on: 000, 003 (complaints), 005 (worker_assignments)
-- ============================================================

-- UNIQUE on worker_assignment_id (not complaint_id): if a complaint is reopened
-- and goes through the loop again with a fresh assignment, it gets its own
-- closure_verifications row. A complaint can have several of these over its
-- lifetime; each worker_assignment gets exactly one.
create table closure_verifications (
  id                   uuid primary key default gen_random_uuid(),
  complaint_id         uuid not null references complaints(id) on delete cascade,
  worker_assignment_id uuid not null unique references worker_assignments(id) on delete cascade,

  reminder_count        smallint not null default 0,
  last_reminder_sent_at timestamptz,

  citizen_confirmed    boolean not null default false,
  citizen_confirmed_at timestamptz,

  reopened      boolean not null default false,
  reopened_at   timestamptz,
  reopen_reason text,
  red_flagged   boolean not null default false,

  created_at timestamptz not null default now(),

  constraint chk_closure_not_both check (not (citizen_confirmed and reopened)),
  constraint chk_closure_reopen_reason check (not reopened or reopen_reason is not null)
);

create index idx_closure_verifications_complaint on closure_verifications (complaint_id);
create index idx_closure_verifications_pending
  on closure_verifications (last_reminder_sent_at)
  where citizen_confirmed = false and reopened = false;

-- ---------- 3-hourly reminder log (drives the 24h citizen-verification window) ----------
create table citizen_verification_reminders (
  id                      uuid primary key default gen_random_uuid(),
  closure_verification_id uuid not null references closure_verifications(id) on delete cascade,
  sent_at                 timestamptz not null default now()
);

create index idx_citizen_reminders_closure on citizen_verification_reminders (closure_verification_id);

create or replace function bump_closure_reminder_count()
returns trigger
language plpgsql
as $$
begin
  update closure_verifications
     set reminder_count = reminder_count + 1,
         last_reminder_sent_at = new.sent_at
   where id = new.closure_verification_id;
  return new;
end;
$$;

create trigger trg_citizen_reminders_bump
  after insert on citizen_verification_reminders
  for each row execute function bump_closure_reminder_count();
