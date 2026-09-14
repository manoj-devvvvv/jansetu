-- ============================================================
-- 016: Master Issue Membership — Support Reclustering
-- Fixes critique #27 (Critical) and documents #28.
-- Depends on: 000, 008
-- ============================================================

-- The inline UNIQUE on complaint_id from 008 permanently locks a complaint to
-- one cluster for its whole lifetime. Recomputing clusters (HDBSCAN re-run,
-- new complaints shifting a cluster's centroid) needs a complaint to be able
-- to move to a different master_issue. Swap "unique forever" for "unique while
-- active", per Design B from the review.
--
-- NOTE: this assumes Postgres's default auto-generated constraint name from an
-- inline `unique` on a single column. If your project renamed it, adjust this
-- one line — everything else in this file is unaffected.
alter table master_issue_members drop constraint master_issue_members_complaint_id_key;

alter table master_issue_members add column is_active boolean not null default true;
alter table master_issue_members add column superseded_at timestamptz;

create unique index uq_master_issue_members_active
  on master_issue_members (complaint_id)
  where is_active = true;

-- Retire any existing active membership for this complaint before the new one
-- is written, so the partial unique index above is never violated.
create or replace function supersede_previous_master_issue_membership()
returns trigger
language plpgsql
as $$
begin
  update master_issue_members
     set is_active = false, superseded_at = now()
   where complaint_id = new.complaint_id
     and is_active = true;
  return new;
end;
$$;

create trigger trg_master_issue_members_supersede
  before insert on master_issue_members
  for each row execute function supersede_previous_master_issue_membership();

-- Replaces the version from 008: member_count must now also react to a
-- membership being superseded (is_active flips true -> false), not just to
-- physical INSERT/DELETE.
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

  elsif tg_op = 'UPDATE' then
    if old.is_active and not new.is_active then
      update master_issues set member_count = greatest(0, member_count - 1), updated_at = now()
       where id = old.master_issue_id;
    elsif not old.is_active and new.is_active then
      update master_issues set member_count = member_count + 1, updated_at = now()
       where id = new.master_issue_id;
    end if;
  end if;

  return null;
end;
$$;

-- The 008 trigger only listened for INSERT/DELETE; widen it to also catch is_active flips.
drop trigger if exists trg_master_issue_members_count on master_issue_members;

create trigger trg_master_issue_members_count
  after insert or delete or update of is_active on master_issue_members
  for each row execute function refresh_master_issue_member_count();

-- Documents critique #28 (resolved vs closed semantics) — a comment, not a
-- structural change, since the actual business rule is a product decision.
comment on column master_issues.status is
  'active: still forming/open. fast_tracked: flagged for priority handling. '
  'resolved: underlying infrastructure problem believed fixed (e.g. member complaints closed). '
  'closed: administratively closed without confirmed resolution (superseded, invalid, or abandoned cluster).';
