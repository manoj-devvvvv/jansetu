-- ============================================================
-- JANSETU DATABASE SCHEMA
-- 000: Extensions, ENUM types, shared helper functions
-- Run this FIRST. Everything else depends on it.
-- ============================================================

-- ---------- Extensions ----------
create extension if not exists pgcrypto;   -- gen_random_uuid()
create extension if not exists postgis;    -- geometry types + spatial indexes
create extension if not exists vector;     -- pgvector: BGE-M3 embeddings for clustering
create extension if not exists pg_trgm;    -- optional: fuzzy text search on formalized complaint text

-- ---------- Shared ENUM types ----------

-- Reused by jurisdictions.level, officers.level, complaints.current_review_level,
-- master_issues.cluster_level, escalations.from_level/to_level. One type, one meaning,
-- used everywhere a panchayat/mandal/district tier needs to be recorded.
create type jurisdiction_level as enum ('panchayat', 'mandal', 'district');

create type complaint_input_mode as enum ('voice', 'text');

-- Set by Gemini/Groq NLU classification during complaint formalization.
-- Consumed by the master-issue clustering job's fast-track decision
-- ("...based on no of complaints and severity").
create type complaint_severity as enum ('low', 'medium', 'high', 'critical');

create type complaint_status as enum (
  'submitted',                      -- freshly filed, sitting in current_review_level's queue
  'waiting',                        -- officer clicked "Wait" (max 2x per complaint, enforced in DB)
  'escalated',                      -- officer clicked "Escalate", or an SLA breach auto-escalated it
  'dismissed',                      -- officer clicked "Dismiss" (terminal)
  'assigned',                       -- worker assigned, SLA clock running, not yet accepted
  'in_progress',                    -- worker accepted and is actively working the job
  'pending_citizen_confirmation',   -- worker uploaded completion photo, awaiting citizen confirm
  'reopened',                       -- citizen rejected the closure -> red-flagged back to officer queue
  'closed'                          -- citizen confirmed resolution (terminal, successful)
);

create type verification_action_type as enum ('verify', 'dismiss', 'wait', 'escalate');

create type assignment_status as enum (
  'assigned', 'accepted', 'worker_excused', 'rejected', 'in_progress', 'completed'
);

create type worker_status as enum ('green', 'yellow', 'red');

create type escalation_trigger_type as enum ('manual', 'sla_breach');

create type sla_tracker_type as enum (
  'worker_assignment', 'panchayat_verification', 'mandal_verification', 'district_verification'
);

create type anomaly_flag_type as enum (
  'impossible_travel', 'fast_completion', 'duplicate_photo', 'model_flagged'
);

create type anomaly_severity as enum ('low', 'medium', 'high');

create type anomaly_review_outcome as enum ('pending', 'confirmed_fraud', 'false_positive');

create type master_issue_status as enum ('active', 'fast_tracked', 'resolved', 'closed');

create type notification_type as enum (
  'assignment', 'sla_reminder', 'citizen_verification_reminder', 'escalation', 'general'
);

-- ---------- Shared helper: generic updated_at trigger ----------
-- Attach this to any table that has an `updated_at timestamptz` column instead of
-- writing a bespoke trigger function per table.
create or replace function set_updated_at()
returns trigger
language plpgsql
as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

comment on function set_updated_at() is
  'Generic BEFORE UPDATE trigger: stamps updated_at = now() on every row update.';
