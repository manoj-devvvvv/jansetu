-- ============================================================
-- 004: Workers + Bulk Upload Batches + Score History
-- Depends on: 000, 001, 002
-- ============================================================

create table worker_bulk_uploads (
  id              uuid primary key default gen_random_uuid(),
  officer_id      uuid not null references officers(id) on delete restrict,
  jurisdiction_id uuid not null references jurisdictions(id) on delete restrict,
  file_name       text not null,
  total_rows      integer not null default 0,
  success_count   integer not null default 0,
  failed_count    integer not null default 0,
  error_report    jsonb not null default '[]'::jsonb,   -- [{"row":4,"error":"invalid phone"}, ...]
  uploaded_at     timestamptz not null default now()
);

create index idx_worker_bulk_uploads_officer on worker_bulk_uploads (officer_id);

-- Status thresholds live in a function (not hardcoded inline in a CHECK/CASE) so
-- they can be changed later with CREATE OR REPLACE FUNCTION. NOTE: because
-- profile_status below is a STORED generated column, changing this function does
-- NOT retroactively recompute existing rows — run a backfill UPDATE afterwards
-- (e.g. `update workers set profile_score = profile_score;`) if thresholds change.
create or replace function compute_worker_status(score smallint)
returns worker_status
language sql
immutable
as $$
  select case
    when score >= 70 then 'green'::worker_status
    when score >= 40 then 'yellow'::worker_status
    else 'red'::worker_status
  end;
$$;

create table workers (
  id                  uuid primary key default gen_random_uuid(),
  mobile_hash         char(64) not null unique,
  login_pin_hash      text not null,     -- bcrypt hash of a short numeric PIN (no OTP/paid SMS gateway)
  full_name           text not null,
  department_id       uuid not null references departments(id) on delete restrict,
  jurisdiction_id     uuid not null references jurisdictions(id) on delete restrict,  -- registered panchayat
  preferred_language  text not null default 'en',
  profile_score       smallint not null default 100 check (profile_score between 0 and 100),
  profile_status      worker_status generated always as (compute_worker_status(profile_score)) stored,
  bulk_upload_id      uuid references worker_bulk_uploads(id) on delete set null,
  is_active           boolean not null default true,
  created_at          timestamptz not null default now(),
  updated_at          timestamptz not null default now()
);

create index idx_workers_jurisdiction on workers (jurisdiction_id);
create index idx_workers_department on workers (department_id);
create index idx_workers_status on workers (profile_status);
create index idx_workers_active on workers (is_active) where is_active = true;

create trigger trg_workers_updated_at
  before update on workers
  for each row execute function set_updated_at();

-- ---------- Append-only score audit log ----------
-- ON DELETE RESTRICT on worker_id: this is an audit ledger, never silently lose it.
create table worker_score_history (
  id                     uuid primary key default gen_random_uuid(),
  worker_id              uuid not null references workers(id) on delete restrict,
  change_amount          smallint not null,     -- positive or negative delta
  reason                 text not null,
  related_assignment_id  uuid,                  -- FK added in 005_worker_assignments.sql (that table doesn't exist yet)
  changed_by             uuid references officers(id) on delete set null,  -- null = automated system change
  created_at             timestamptz not null default now(),
  constraint chk_worker_score_change_nonzero check (change_amount <> 0)
);

create index idx_worker_score_history_worker on worker_score_history (worker_id);

-- Keep workers.profile_score in sync with the audit log automatically —
-- callers only ever INSERT into worker_score_history, never UPDATE workers directly.
create or replace function apply_worker_score_change()
returns trigger
language plpgsql
as $$
begin
  update workers
     set profile_score = greatest(0, least(100, profile_score + new.change_amount)),
         updated_at = now()
   where id = new.worker_id;
  return new;
end;
$$;

create trigger trg_worker_score_history_apply
  after insert on worker_score_history
  for each row execute function apply_worker_score_change();
