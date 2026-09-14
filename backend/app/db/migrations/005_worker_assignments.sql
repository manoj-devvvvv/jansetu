-- ============================================================
-- 005: Worker Assignments (accept / excuse / leave, arrival + completion)
-- Depends on: 000, 003 (complaints), 004 (workers)
-- ============================================================

create table worker_assignments (
  id           uuid primary key default gen_random_uuid(),
  complaint_id uuid not null references complaints(id) on delete restrict,
  worker_id    uuid not null references workers(id) on delete restrict,
  status       assignment_status not null default 'assigned',

  assigned_at  timestamptz not null default now(),
  accepted_at  timestamptz,

  excuse_used  boolean not null default false,   -- flips true via worker_excuses trigger (file 006)

  rejected_at     timestamptz,
  rejected_reason text,

  arrival_photo_url text,
  arrival_location  geometry(Point, 4326),
  arrived_at        timestamptz,

  completion_photo_url text,
  completion_location  geometry(Point, 4326),
  completed_at         timestamptz,

  created_at   timestamptz not null default now(),
  updated_at   timestamptz not null default now(),

  constraint chk_worker_assignments_rejection check (status <> 'rejected' or rejected_reason is not null)
);

create index idx_worker_assignments_complaint on worker_assignments (complaint_id);
create index idx_worker_assignments_worker on worker_assignments (worker_id);
create index idx_worker_assignments_status on worker_assignments (status);
create index idx_worker_assignments_arrival_gist on worker_assignments using gist (arrival_location);
create index idx_worker_assignments_completion_gist on worker_assignments using gist (completion_location);

create trigger trg_worker_assignments_updated_at
  before update on worker_assignments
  for each row execute function set_updated_at();

-- Now that worker_assignments exists, wire up the FK deferred from 004_workers.sql
alter table worker_score_history
  add constraint fk_worker_score_history_assignment
  foreign key (related_assignment_id) references worker_assignments(id) on delete set null;

create index idx_worker_score_history_assignment on worker_score_history (related_assignment_id);
