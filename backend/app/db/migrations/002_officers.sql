-- ============================================================
-- 002: Officers (Panchayat / Mandal / District), linked to Supabase Auth
-- Depends on: 000, 001
-- ============================================================

create table officers (
  id              uuid primary key references auth.users(id) on delete cascade,
  full_name       text not null,
  level           jurisdiction_level not null,
  jurisdiction_id uuid not null references jurisdictions(id) on delete restrict,
  is_active       boolean not null default true,
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now()
);

-- Email/login lives in auth.users (Supabase Auth). The FastAPI backend connects
-- with a service-role/direct Postgres connection and can join officers -> auth.users
-- on id whenever email is needed, so it is intentionally NOT duplicated here.
--
-- Operational note: other tables (complaint_verification_actions, escalations, etc.)
-- reference officers(id) with ON DELETE RESTRICT to protect audit history. That
-- means deleting the underlying auth.users row will fail once an officer has any
-- logged action. Prefer soft-deleting via is_active = false over a hard delete.

create index idx_officers_jurisdiction on officers (jurisdiction_id);
create index idx_officers_level on officers (level);

create trigger trg_officers_updated_at
  before update on officers
  for each row execute function set_updated_at();

-- Enforce that officers.level matches the level of their assigned jurisdiction row
-- (a 'mandal' officer must point to a jurisdiction with level = 'mandal', etc.)
create or replace function enforce_officer_jurisdiction_level()
returns trigger
language plpgsql
as $$
declare
  j_level jurisdiction_level;
begin
  select level into j_level from jurisdictions where id = new.jurisdiction_id;

  if j_level is null then
    raise exception 'jurisdiction_id % does not exist', new.jurisdiction_id;
  end if;

  if j_level <> new.level then
    raise exception 'Officer level (%) does not match jurisdiction level (%)', new.level, j_level;
  end if;

  return new;
end;
$$;

create trigger trg_officers_jurisdiction_level
  before insert or update of level, jurisdiction_id on officers
  for each row execute function enforce_officer_jurisdiction_level();
