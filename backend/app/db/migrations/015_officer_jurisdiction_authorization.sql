-- ============================================================
-- 015: Officer <-> Jurisdiction Authorization
-- Fixes critique #5 and #13 (both Critical in the summary table).
-- Depends on: 000, 001, 002, 003, 004, 006
-- ============================================================

-- Small reusable helper: which jurisdiction a complaint belongs to at a given level.
create or replace function complaint_jurisdiction_at_level(p_complaint_id uuid, p_level jurisdiction_level)
returns uuid
language sql
stable
as $$
  select case p_level
           when 'panchayat' then panchayat_id
           when 'mandal'    then mandal_id
           when 'district'  then district_id
         end
    from complaints
   where id = p_complaint_id;
$$;


-- ---------- 1. Verification actions: officer must own the complaint's current level ----------
-- Nullable: rows written before this migration have no recorded review_level.
alter table complaint_verification_actions add column review_level jurisdiction_level;

create or replace function enforce_verification_action_authorization()
returns trigger
language plpgsql
as $$
declare
  officer_level        jurisdiction_level;
  officer_jurisdiction  uuid;
  complaint_review_level jurisdiction_level;
  expected_jurisdiction uuid;
begin
  select level, jurisdiction_id into officer_level, officer_jurisdiction
    from officers where id = new.officer_id;

  select current_review_level into complaint_review_level
    from complaints where id = new.complaint_id;

  if officer_level is distinct from complaint_review_level then
    raise exception 'Officer level (%) does not match the complaint''s current review level (%)',
      officer_level, complaint_review_level;
  end if;

  expected_jurisdiction := complaint_jurisdiction_at_level(new.complaint_id, officer_level);

  if officer_jurisdiction is distinct from expected_jurisdiction then
    raise exception 'Officer''s jurisdiction does not match the complaint''s % jurisdiction', officer_level;
  end if;

  new.review_level := officer_level;
  return new;
end;
$$;

create trigger trg_verification_actions_authorization
  before insert on complaint_verification_actions
  for each row execute function enforce_verification_action_authorization();


-- ---------- 2. Escalations: the escalating officer must own the from_level ----------
-- Only checked for manual escalations; SLA-breach escalations have no human officer.
create or replace function enforce_escalation_authorization()
returns trigger
language plpgsql
as $$
declare
  officer_level        jurisdiction_level;
  officer_jurisdiction  uuid;
  expected_jurisdiction uuid;
begin
  if new.trigger_type <> 'manual' or new.escalated_by is null then
    return new;
  end if;

  select level, jurisdiction_id into officer_level, officer_jurisdiction
    from officers where id = new.escalated_by;

  if officer_level is distinct from new.from_level then
    raise exception 'Escalating officer''s level (%) does not match from_level (%)', officer_level, new.from_level;
  end if;

  expected_jurisdiction := complaint_jurisdiction_at_level(new.complaint_id, officer_level);

  if officer_jurisdiction is distinct from expected_jurisdiction then
    raise exception 'Escalating officer''s jurisdiction does not match the complaint''s % jurisdiction', officer_level;
  end if;

  return new;
end;
$$;

create trigger trg_escalations_authorization
  before insert on escalations
  for each row execute function enforce_escalation_authorization();


-- ---------- 3. Worker uploads: only a panchayat officer, for their own panchayat ----------
create or replace function enforce_worker_bulk_upload_authorization()
returns trigger
language plpgsql
as $$
declare
  officer_level       jurisdiction_level;
  officer_jurisdiction uuid;
begin
  select level, jurisdiction_id into officer_level, officer_jurisdiction
    from officers where id = new.officer_id;

  if officer_level <> 'panchayat' then
    raise exception 'Only panchayat-level officers upload worker batches (officer level: %)', officer_level;
  end if;

  if officer_jurisdiction <> new.jurisdiction_id then
    raise exception 'Officer may only upload workers for their own panchayat';
  end if;

  return new;
end;
$$;

create trigger trg_worker_bulk_uploads_authorization
  before insert on worker_bulk_uploads
  for each row execute function enforce_worker_bulk_upload_authorization();


-- ---------- 4. Workers: jurisdiction must agree with however they were created ----------
alter table workers add column created_by_officer_id uuid references officers(id) on delete set null;

create or replace function enforce_worker_jurisdiction_consistency()
returns trigger
language plpgsql
as $$
declare
  batch_jurisdiction   uuid;
  officer_level        jurisdiction_level;
  officer_jurisdiction uuid;
begin
  if new.bulk_upload_id is not null then
    select jurisdiction_id into batch_jurisdiction
      from worker_bulk_uploads where id = new.bulk_upload_id;

    if new.jurisdiction_id is distinct from batch_jurisdiction then
      raise exception 'worker.jurisdiction_id must match its bulk_upload batch''s jurisdiction_id';
    end if;
  end if;

  if new.created_by_officer_id is not null then
    select level, jurisdiction_id into officer_level, officer_jurisdiction
      from officers where id = new.created_by_officer_id;

    if officer_level <> 'panchayat' or officer_jurisdiction <> new.jurisdiction_id then
      raise exception 'Officer may only register workers for their own panchayat';
    end if;
  end if;

  return new;
end;
$$;

create trigger trg_workers_jurisdiction_consistency
  before insert or update of bulk_upload_id, created_by_officer_id, jurisdiction_id on workers
  for each row execute function enforce_worker_jurisdiction_consistency();
