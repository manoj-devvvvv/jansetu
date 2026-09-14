-- ============================================================
-- 008: Hyperlocal Master Issue Clustering (pgvector + HDBSCAN inputs)
-- Depends on: 000, 001 (departments/jurisdictions), 003 (complaints)
-- ============================================================

-- ---------- BGE-M3 embeddings (1024-dim dense vectors) ----------
create table complaint_embeddings (
  id            uuid primary key default gen_random_uuid(),
  complaint_id  uuid not null unique references complaints(id) on delete cascade,
  embedding     vector(1024) not null,
  model_version text not null default 'bge-m3',
  created_at    timestamptz not null default now()
);

-- Cosine-similarity ANN index for "find semantically similar complaints" queries.
-- Requires pgvector >= 0.5.0. If your Supabase project predates that, replace with:
--   create index idx_complaint_embeddings_ivfflat on complaint_embeddings
--     using ivfflat (embedding vector_cosine_ops) with (lists = 100);
create index idx_complaint_embeddings_hnsw
  on complaint_embeddings using hnsw (embedding vector_cosine_ops);

-- Supports the pre-filter step (same department + same panchayat) that narrows
-- the candidate set before the ANN similarity search runs.
create index idx_complaints_dept_panchayat on complaints (department_id, panchayat_id);


-- ---------- Master issues (the clustered result) ----------
create table master_issues (
  id                           uuid primary key default gen_random_uuid(),
  department_id                uuid not null references departments(id) on delete restrict,
  jurisdiction_id              uuid not null references jurisdictions(id) on delete restrict,  -- panchayat OR mandal row
  cluster_level                jurisdiction_level not null,
  representative_complaint_id  uuid references complaints(id) on delete set null,
  centroid_location            geometry(Point, 4326),
  confidence_score             numeric(5,4) check (confidence_score between 0 and 1),
  member_count                 integer not null default 0,   -- denormalized, maintained by trigger below
  status                       master_issue_status not null default 'active',
  is_fast_tracked               boolean not null default false,
  fast_tracked_at              timestamptz,
  created_at                   timestamptz not null default now(),
  updated_at                   timestamptz not null default now(),

  constraint chk_master_issue_cluster_level check (cluster_level in ('panchayat', 'mandal'))
);

create index idx_master_issues_jurisdiction on master_issues (jurisdiction_id);
create index idx_master_issues_department on master_issues (department_id);
create index idx_master_issues_status on master_issues (status);
create index idx_master_issues_centroid_gist on master_issues using gist (centroid_location);

create trigger trg_master_issues_updated_at
  before update on master_issues
  for each row execute function set_updated_at();

-- Guard against jurisdiction_id/cluster_level disagreeing (e.g. cluster_level =
-- 'panchayat' but jurisdiction_id actually points at a mandal row).
create or replace function validate_master_issue_jurisdiction_level()
returns trigger
language plpgsql
as $$
declare
  j_level jurisdiction_level;
begin
  select level into j_level from jurisdictions where id = new.jurisdiction_id;
  if j_level is distinct from new.cluster_level then
    raise exception 'master_issues.jurisdiction_id level (%) does not match cluster_level (%)',
      j_level, new.cluster_level;
  end if;
  return new;
end;
$$;

create trigger trg_master_issues_validate_level
  before insert or update of jurisdiction_id, cluster_level on master_issues
  for each row execute function validate_master_issue_jurisdiction_level();


-- ---------- Master issue membership (one active cluster per complaint) ----------
create table master_issue_members (
  id               uuid primary key default gen_random_uuid(),
  master_issue_id  uuid not null references master_issues(id) on delete cascade,
  complaint_id     uuid not null unique references complaints(id) on delete cascade,
  similarity_score numeric(5,4) check (similarity_score between 0 and 1),
  joined_at        timestamptz not null default now()
);

create index idx_master_issue_members_issue on master_issue_members (master_issue_id);

-- Keep master_issues.member_count accurate automatically.
create or replace function refresh_master_issue_member_count()
returns trigger
language plpgsql
as $$
begin
  if tg_op = 'INSERT' then
    update master_issues set member_count = member_count + 1, updated_at = now()
     where id = new.master_issue_id;
  elsif tg_op = 'DELETE' then
    update master_issues set member_count = greatest(0, member_count - 1), updated_at = now()
     where id = old.master_issue_id;
  end if;
  return null;
end;
$$;

create trigger trg_master_issue_members_count
  after insert or delete on master_issue_members
  for each row execute function refresh_master_issue_member_count();
