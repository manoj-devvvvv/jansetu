-- ============================================================
-- 003: Citizens + Complaints + Complaint Image Validation (YOLO)
-- Depends on: 000, 001
-- ============================================================

-- No login/OTP: a citizen is identified purely by a hashed mobile number
-- (SHA-256 + server-side pepper, computed in the app layer — never store plaintext).
create table citizens (
  id                      uuid primary key default gen_random_uuid(),
  mobile_hash             char(64) not null unique,
  preferred_language      text not null default 'en',
  total_complaints_filed  integer not null default 0,   -- denormalized, maintained by trigger below
  is_blocked              boolean not null default false,
  created_at              timestamptz not null default now(),
  updated_at              timestamptz not null default now()
);

create trigger trg_citizens_updated_at
  before update on citizens
  for each row execute function set_updated_at();

-- ---------- Complaints ----------
create table complaints (
  id            uuid primary key default gen_random_uuid(),
  citizen_id    uuid not null references citizens(id) on delete restrict,
  department_id uuid not null references departments(id) on delete restrict,

  -- Denormalized jurisdiction chain, resolved once at submission time via the
  -- PostGIS + Nominatim lookup service. Kept flat so mandal/district dashboards
  -- can filter/aggregate without recursive parent_id walks on every query.
  -- Integrity across the three is enforced by the trigger further below —
  -- this is the one place a hand-written INSERT could otherwise go wrong.
  panchayat_id  uuid not null references jurisdictions(id) on delete restrict,
  mandal_id     uuid not null references jurisdictions(id) on delete restrict,
  district_id   uuid not null references jurisdictions(id) on delete restrict,

  current_review_level jurisdiction_level not null default 'panchayat',

  location      geometry(Point, 4326) not null,

  input_mode    complaint_input_mode not null,
  voice_audio_url text,
  raw_text        text,      -- text mode: given directly. voice mode: filled async by Groq Whisper.
  formalized_text text,      -- Gemini/Groq-normalized complaint description
  detected_language text,
  transcription_confidence numeric(4,3),

  severity      complaint_severity not null default 'medium',  -- set by NLU classification

  image_url     text not null,

  submitter_ip  inet not null,   -- backs the 2-complaints/day/IP rate limit

  status        complaint_status not null default 'submitted',
  wait_count    smallint not null default 0,   -- authoritative counter for the max-2-"wait" rule

  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now(),
  resolved_at   timestamptz,
  closed_at     timestamptz,

  constraint chk_complaints_voice_has_audio check (input_mode <> 'voice' or voice_audio_url is not null),
  constraint chk_complaints_wait_count_range check (wait_count between 0 and 2)
);

create index idx_complaints_location_gist on complaints using gist (location);
create index idx_complaints_panchayat_status on complaints (panchayat_id, status);
create index idx_complaints_mandal_status on complaints (mandal_id, status);
create index idx_complaints_district_status on complaints (district_id, status);
create index idx_complaints_department on complaints (department_id);
create index idx_complaints_citizen on complaints (citizen_id);
create index idx_complaints_current_review_level on complaints (current_review_level, status);
create index idx_complaints_rate_limit_ip on complaints (submitter_ip, created_at);
create index idx_complaints_created_at on complaints (created_at);

create trigger trg_complaints_updated_at
  before update on complaints
  for each row execute function set_updated_at();

-- Keep citizens.total_complaints_filed accurate without relying on the app layer
create or replace function bump_citizen_complaint_count()
returns trigger
language plpgsql
as $$
begin
  update citizens
     set total_complaints_filed = total_complaints_filed + 1,
         updated_at = now()
   where id = new.citizen_id;
  return new;
end;
$$;

create trigger trg_complaints_bump_citizen_count
  after insert on complaints
  for each row execute function bump_citizen_complaint_count();

-- Guard the denormalized jurisdiction chain: panchayat_id must actually be a
-- panchayat whose parent is mandal_id, and mandal_id must actually be a mandal
-- whose parent is district_id. This is the exact class of bug denormalization
-- risks, so it's enforced here rather than trusted to the API layer.
create or replace function validate_complaint_jurisdiction_chain()
returns trigger
language plpgsql
as $$
declare
  p_level jurisdiction_level;
  p_parent uuid;
  m_level jurisdiction_level;
  m_parent uuid;
  d_level jurisdiction_level;
begin
  select level, parent_id into p_level, p_parent from jurisdictions where id = new.panchayat_id;
  select level, parent_id into m_level, m_parent from jurisdictions where id = new.mandal_id;
  select level into d_level from jurisdictions where id = new.district_id;

  if p_level is distinct from 'panchayat' then
    raise exception 'complaints.panchayat_id must reference a panchayat-level jurisdiction';
  end if;
  if m_level is distinct from 'mandal' then
    raise exception 'complaints.mandal_id must reference a mandal-level jurisdiction';
  end if;
  if d_level is distinct from 'district' then
    raise exception 'complaints.district_id must reference a district-level jurisdiction';
  end if;
  if p_parent is distinct from new.mandal_id then
    raise exception 'complaints.panchayat_id does not belong to the given mandal_id';
  end if;
  if m_parent is distinct from new.district_id then
    raise exception 'complaints.mandal_id does not belong to the given district_id';
  end if;

  return new;
end;
$$;

create trigger trg_complaints_validate_jurisdiction
  before insert or update of panchayat_id, mandal_id, district_id on complaints
  for each row execute function validate_complaint_jurisdiction_chain();

-- ---------- YOLO image validation result (1:1 with complaints) ----------
create table complaint_image_validations (
  id               uuid primary key default gen_random_uuid(),
  complaint_id     uuid not null unique references complaints(id) on delete cascade,
  model_name       text not null default 'yolo11',
  detected_labels  jsonb not null default '[]'::jsonb,
  confidence       numeric(5,4) check (confidence between 0 and 1),
  is_valid         boolean not null,
  rejection_reason text,
  validated_at     timestamptz not null default now()
);

create index idx_civ_complaint on complaint_image_validations (complaint_id);
