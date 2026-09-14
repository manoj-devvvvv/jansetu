-- ============================================================
-- 009: AI-Driven Anomaly & Fraud Detection for Field Workers
-- Depends on: 000, 002 (officers), 004 (workers), 005 (worker_assignments)
-- ============================================================

-- ---------- Per-completion feature vector (XGBoost input) ----------
-- Derived/computed data, scoped 1:1 to a single assignment attempt — cascades
-- with the assignment since it has no standalone meaning without it.
create table worker_completion_features (
  id                                 uuid primary key default gen_random_uuid(),
  worker_assignment_id               uuid not null unique references worker_assignments(id) on delete cascade,
  distance_from_previous_job_meters  numeric,
  time_since_previous_job_seconds    integer,
  implied_travel_speed_kmph          numeric,
  completion_duration_seconds        integer,
  is_duplicate_photo                 boolean not null default false,
  anomaly_score                      numeric(5,4) check (anomaly_score between 0 and 1),
  feature_vector                     jsonb not null default '{}'::jsonb,  -- full raw features, for retraining/audit
  computed_at                        timestamptz not null default now()
);

create index idx_completion_features_score on worker_completion_features (anomaly_score);

-- ---------- Flags raised for human review ----------
-- This is the audit-of-record for fraud findings, so both FKs are RESTRICT:
-- a confirmed_fraud flag must never silently disappear because a worker or
-- assignment row was removed.
create table anomaly_flags (
  id                   uuid primary key default gen_random_uuid(),
  worker_id            uuid not null references workers(id) on delete restrict,
  worker_assignment_id uuid not null references worker_assignments(id) on delete restrict,
  flag_type            anomaly_flag_type not null,
  severity             anomaly_severity not null,
  anomaly_score        numeric(5,4) check (anomaly_score between 0 and 1),
  review_outcome       anomaly_review_outcome not null default 'pending',
  reviewed_by          uuid references officers(id) on delete set null,
  reviewed_at          timestamptz,
  created_at           timestamptz not null default now(),

  constraint chk_anomaly_review_consistency
    check (review_outcome = 'pending' or (reviewed_by is not null and reviewed_at is not null))
);

create index idx_anomaly_flags_worker on anomaly_flags (worker_id);
create index idx_anomaly_flags_pending on anomaly_flags (review_outcome) where review_outcome = 'pending';

-- ---------- Photo hash registry (exact + perceptual duplicate detection) ----------
create table photo_hash_registry (
  id                   uuid primary key default gen_random_uuid(),
  worker_id            uuid not null references workers(id) on delete cascade,
  worker_assignment_id uuid not null unique references worker_assignments(id) on delete cascade,
  photo_sha256         char(64) not null,   -- exact byte-identical duplicate detection
  photo_phash          bigint not null,     -- 64-bit perceptual hash; near-duplicate check is done
                                             -- app-side via Hamming distance over each worker's rows
                                             -- (no native Postgres index type for Hamming distance)
  created_at           timestamptz not null default now()
);

create index idx_photo_hash_sha256 on photo_hash_registry (photo_sha256);
create index idx_photo_hash_worker on photo_hash_registry (worker_id);
