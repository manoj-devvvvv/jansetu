-- ============================================================
-- 010: Proactive Intelligence — Recurring Issues + Analytics Views
-- Depends on: 001, 003, 005, 006, 008
-- ============================================================

create table recurring_issue_patterns (
  id                        uuid primary key default gen_random_uuid(),
  jurisdiction_id           uuid not null references jurisdictions(id) on delete cascade,
  department_id             uuid not null references departments(id) on delete cascade,
  pattern_month             smallint check (pattern_month between 1 and 12),
  occurrence_years          integer[] not null default '{}',
  recurrence_count          integer not null default 0,
  confidence_score          numeric(5,4) check (confidence_score between 0 and 1),
  description               text,
  related_master_issue_ids  uuid[] not null default '{}',  -- traceability only, not a hard FK (array of uuid)
  first_detected_at         timestamptz not null default now(),
  last_detected_at          timestamptz not null default now(),
  is_active                 boolean not null default true
);

create index idx_recurring_patterns_jurisdiction on recurring_issue_patterns (jurisdiction_id, department_id);
create index idx_recurring_patterns_active on recurring_issue_patterns (is_active) where is_active = true;


-- ---------- Materialized views for officer analytics dashboards (Apache ECharts) ----------

create materialized view mv_quarterly_complaint_summary as
select
  panchayat_id,
  mandal_id,
  district_id,
  department_id,
  date_trunc('quarter', created_at) as quarter_start,
  status,
  count(*) as complaint_count,
  avg(extract(epoch from (resolved_at - created_at)) / 3600.0)
    filter (where resolved_at is not null) as avg_resolution_hours
from complaints
group by panchayat_id, mandal_id, district_id, department_id, quarter_start, status;

create unique index uq_mv_quarterly_summary
  on mv_quarterly_complaint_summary (panchayat_id, department_id, quarter_start, status);

create materialized view mv_sla_compliance as
select
  c.panchayat_id,
  c.mandal_id,
  c.district_id,
  c.department_id,
  date_trunc('quarter', st.started_at) as quarter_start,
  st.tracker_type,
  count(*) as total_trackers,
  count(*) filter (where st.breached) as breached_count
from sla_trackers st
left join worker_assignments wa on wa.id = st.worker_assignment_id
join complaints c on c.id = coalesce(st.complaint_id, wa.complaint_id)
group by c.panchayat_id, c.mandal_id, c.district_id, c.department_id, quarter_start, st.tracker_type;

create unique index uq_mv_sla_compliance
  on mv_sla_compliance (panchayat_id, department_id, quarter_start, tracker_type);

-- Refresh both views periodically from APScheduler, e.g. nightly:
--   REFRESH MATERIALIZED VIEW CONCURRENTLY mv_quarterly_complaint_summary;
--   REFRESH MATERIALIZED VIEW CONCURRENTLY mv_sla_compliance;
-- CONCURRENTLY needs the unique indexes above and doesn't block concurrent reads.
