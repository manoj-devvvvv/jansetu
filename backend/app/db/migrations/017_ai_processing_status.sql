-- ============================================================
-- 017: AI Processing Status (separate from complaints.status)
-- Fixes critique #42 (High).
-- Depends on: 000, 003
-- ============================================================

create type ai_processing_status as enum ('pending', 'processing', 'completed', 'failed');

-- One row per complaint, auto-created at submission time, tracking each async
-- pipeline stage independently of the citizen-facing complaint.status. Celery
-- tasks update these as they run instead of overloading complaint_status.
create table complaint_processing_status (
  complaint_id            uuid primary key references complaints(id) on delete cascade,
  transcription_status    ai_processing_status not null default 'pending',  -- voice mode only
  formalization_status    ai_processing_status not null default 'pending',  -- Gemini/Groq NLU
  image_validation_status ai_processing_status not null default 'pending',  -- YOLO
  embedding_status        ai_processing_status not null default 'pending',  -- BGE-M3 + clustering
  updated_at              timestamptz not null default now()
);

create trigger trg_complaint_processing_status_updated_at
  before update on complaint_processing_status
  for each row execute function set_updated_at();

-- Text-mode complaints have nothing to transcribe, so start that stage as
-- already-completed instead of leaving it perpetually 'pending'.
create or replace function create_complaint_processing_status()
returns trigger
language plpgsql
as $$
begin
  insert into complaint_processing_status (complaint_id, transcription_status)
  values (new.id, case when new.input_mode = 'text' then 'completed' else 'pending' end);
  return new;
end;
$$;

create trigger trg_complaints_create_processing_status
  after insert on complaints
  for each row execute function create_complaint_processing_status();

-- Backfill for any complaint that already existed before this migration.
-- Idempotent, and a no-op on a table with no prior rows.
insert into complaint_processing_status (complaint_id, transcription_status)
select c.id, case when c.input_mode = 'text' then 'completed' else 'pending' end
  from complaints c
 where not exists (
   select 1 from complaint_processing_status p where p.complaint_id = c.id
 );

alter table complaint_processing_status enable row level security;
alter table complaint_processing_status force row level security;
