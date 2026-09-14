-- ============================================================
-- 001: Departments (reference data) + Jurisdictions (panchayat/mandal/district)
-- Depends on: 000
-- ============================================================

create table departments (
  id            uuid primary key default gen_random_uuid(),
  code          text not null unique,                  -- 'water','drainage','roads','electricity','hospital'
  name_i18n     jsonb not null default '{}'::jsonb,     -- {"en":"Water","hi":"...","te":"..."}
  icon_key      text not null,                          -- frontend icon identifier
  display_order smallint not null default 0,
  is_active     boolean not null default true,
  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now(),
  constraint chk_departments_name_en check (name_i18n ? 'en')
);

create trigger trg_departments_updated_at
  before update on departments
  for each row execute function set_updated_at();

create index idx_departments_active on departments (is_active) where is_active = true;

-- Seed the 5 departments named in the spec. Add hi/te keys to name_i18n once
-- translations are finalized; 'en' is the only key required by the CHECK above.
insert into departments (code, name_i18n, icon_key, display_order) values
  ('water',       '{"en":"Water"}'::jsonb,          'icon-tap',         1),
  ('drainage',    '{"en":"Drainage"}'::jsonb,       'icon-drainage',    2),
  ('roads',       '{"en":"Roads"}'::jsonb,          'icon-road',        3),
  ('electricity', '{"en":"Electricity"}'::jsonb,    'icon-electricity', 4),
  ('hospital',    '{"en":"Basti Hospital"}'::jsonb, 'icon-hospital',    5);


-- ---------- Jurisdictions ----------
-- Self-referencing hierarchy: panchayat -> mandal -> district.
-- Stored as `geometry` (not `geography`): ST_Contains/ST_Covers and GIST perform
-- best on geometry at this local scale. Cast to ::geography when you need a
-- real-world distance/area figure (e.g. ST_Distance(a::geography, b::geography)).
create table jurisdictions (
  id           uuid primary key default gen_random_uuid(),
  level        jurisdiction_level not null,
  parent_id    uuid references jurisdictions(id) on delete restrict,
  name_i18n    jsonb not null default '{}'::jsonb,
  lgd_code     text,                                   -- Local Government Directory code, if available
  boundary     geometry(MultiPolygon, 4326),            -- loaded from govt shapefiles after creation
  centroid     geometry(Point, 4326),                   -- auto-derived from boundary, see trigger below
  created_at   timestamptz not null default now(),
  updated_at   timestamptz not null default now(),

  constraint chk_jurisdictions_name_en check (name_i18n ? 'en'),
  -- A district has no parent; a panchayat/mandal must have one. Single boolean
  -- equivalence instead of two separate checks, so there's exactly one rule to read.
  constraint chk_jurisdictions_parent_matches_level check ((level = 'district') = (parent_id is null))
);

create unique index uq_jurisdictions_lgd_code on jurisdictions (lgd_code) where lgd_code is not null;
create index idx_jurisdictions_parent on jurisdictions (parent_id);
create index idx_jurisdictions_level on jurisdictions (level);
create index idx_jurisdictions_boundary_gist on jurisdictions using gist (boundary);
create index idx_jurisdictions_centroid_gist on jurisdictions using gist (centroid);

create trigger trg_jurisdictions_updated_at
  before update on jurisdictions
  for each row execute function set_updated_at();

-- Enforce that a jurisdiction's parent is exactly one level up
-- (panchayat's parent must be a mandal; mandal's parent must be a district).
create or replace function enforce_jurisdiction_hierarchy()
returns trigger
language plpgsql
as $$
declare
  parent_level jurisdiction_level;
begin
  if new.parent_id is null then
    return new; -- only valid for 'district', already enforced by the CHECK constraint
  end if;

  select level into parent_level from jurisdictions where id = new.parent_id;

  if new.level = 'panchayat' and parent_level <> 'mandal' then
    raise exception 'A panchayat''s parent jurisdiction must be a mandal (got %)', parent_level;
  elsif new.level = 'mandal' and parent_level <> 'district' then
    raise exception 'A mandal''s parent jurisdiction must be a district (got %)', parent_level;
  end if;

  return new;
end;
$$;

create trigger trg_jurisdictions_hierarchy
  before insert or update of level, parent_id on jurisdictions
  for each row execute function enforce_jurisdiction_hierarchy();

-- Auto-derive centroid whenever boundary is set/changed, so it never drifts out of sync.
create or replace function set_jurisdiction_centroid()
returns trigger
language plpgsql
as $$
begin
  if new.boundary is not null then
    new.centroid := ST_Centroid(new.boundary);
  end if;
  return new;
end;
$$;

create trigger trg_jurisdictions_centroid
  before insert or update of boundary on jurisdictions
  for each row execute function set_jurisdiction_centroid();
