-- ============================================================
-- 019: Closure Deadline + Materialized View Index Fix
-- Fixes critique #24 and #34/#35 (High).
-- Depends on: 000, 007, 010
-- ============================================================

-- ---------- #24: explicit 24h citizen-verification deadline ----------
-- NOTE: this is NOT a `GENERATED ... STORED` column on purpose. Postgres's
-- timestamptz + interval operator is catalogued STABLE (interval day/month
-- components are timezone-dependent), not IMMUTABLE — a generated column
-- using it fails at creation time with "generation expression is not
-- immutable". A plain column set by a BEFORE INSERT trigger has no such
-- restriction and is exact, since NEW.created_at is already resolved (from
-- either an explicit value or its own DEFAULT now()) by the time a BEFORE
-- INSERT trigger runs.
alter table closure_verifications add column verification_due_at timestamptz;

create or replace function set_closure_verification_due_at()
returns trigger
language plpgsql
as $$
begin
  new.verification_due_at := new.created_at + interval '24 hours';
  return new;
end;
$$;

create trigger trg_closure_verifications_due_at
  before insert on closure_verifications
  for each row execute function set_closure_verification_due_at();

-- Backfill for any row that already existed before this migration. Idempotent
-- (only touches rows still NULL), and a no-op on a table with no prior rows.
update closure_verifications
   set verification_due_at = created_at + interval '24 hours'
 where verification_due_at is null;

create index idx_closure_verifications_due on closure_verifications (verification_due_at)
  where citizen_confirmed = false and reopened = false;


-- ---------- #34/#35: unique indexes didn't match the views' full GROUP BY key ----------
-- panchayat_id -> mandal_id -> district_id is only a *fixed* function today.
-- If jurisdiction boundaries are ever administratively reorganized (a panchayat
-- moved to a different mandal), two complaints created before/after that change
-- could carry the same panchayat_id with different mandal_id/district_id, and
-- the narrower index below would then reject a legitimate distinct row. Widen
-- both indexes to match their GROUP BY exactly — safe regardless of whether
-- reorganization ever actually happens.
drop index uq_mv_quarterly_summary;
create unique index uq_mv_quarterly_summary
  on mv_quarterly_complaint_summary (panchayat_id, mandal_id, district_id, department_id, quarter_start, status);

drop index uq_mv_sla_compliance;
create unique index uq_mv_sla_compliance
  on mv_sla_compliance (panchayat_id, mandal_id, district_id, department_id, quarter_start, tracker_type);
