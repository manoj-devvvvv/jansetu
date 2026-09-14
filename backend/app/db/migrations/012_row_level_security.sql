-- ============================================================
-- 012: Row Level Security
-- ------------------------------------------------------------
-- Architecture note: the FastAPI backend is the ONLY reader/writer of this
-- schema. It connects with the Supabase service_role key (or a direct Postgres
-- connection string) — service_role has the BYPASSRLS attribute and ignores
-- RLS/FORCE RLS entirely, regardless of what's configured below. Supabase Auth
-- is used only to ISSUE officer JWTs; the officer web app does not talk to
-- PostgREST/a browser-side Supabase client for data.
--
-- Given that, the correct default is: enable RLS on every table, and add NO
-- permissive policies. The anon/authenticated roles (used by PostgREST or a
-- browser-side Supabase client) get zero access to any row; the FastAPI
-- service-role connection is completely unaffected.
--
-- If a future requirement has a Next.js app query Supabase directly (bypassing
-- FastAPI) for some read path, add a narrow, explicit SELECT policy at that
-- time — don't widen this file speculatively.
--
-- NOTE: mv_quarterly_complaint_summary and mv_sla_compliance are materialized
-- VIEWS, not tables — Postgres does not support RLS on views/matviews. Do not
-- GRANT SELECT on them to anon/authenticated (the Postgres default already
-- withholds it unless explicitly granted).
-- ============================================================

alter table departments enable row level security;
alter table jurisdictions enable row level security;
alter table officers enable row level security;
alter table citizens enable row level security;
alter table complaints enable row level security;
alter table complaint_image_validations enable row level security;
alter table worker_bulk_uploads enable row level security;
alter table workers enable row level security;
alter table worker_score_history enable row level security;
alter table worker_assignments enable row level security;
alter table sla_configs enable row level security;
alter table sla_trackers enable row level security;
alter table worker_excuses enable row level security;
alter table complaint_verification_actions enable row level security;
alter table escalations enable row level security;
alter table closure_verifications enable row level security;
alter table citizen_verification_reminders enable row level security;
alter table complaint_embeddings enable row level security;
alter table master_issues enable row level security;
alter table master_issue_members enable row level security;
alter table worker_completion_features enable row level security;
alter table anomaly_flags enable row level security;
alter table photo_hash_registry enable row level security;
alter table recurring_issue_patterns enable row level security;
alter table push_subscriptions enable row level security;
alter table notification_log enable row level security;

-- FORCE also applies RLS to the table owner as an extra safety net.
-- (service_role still bypasses everything via BYPASSRLS regardless.)
alter table departments force row level security;
alter table jurisdictions force row level security;
alter table officers force row level security;
alter table citizens force row level security;
alter table complaints force row level security;
alter table complaint_image_validations force row level security;
alter table worker_bulk_uploads force row level security;
alter table workers force row level security;
alter table worker_score_history force row level security;
alter table worker_assignments force row level security;
alter table sla_configs force row level security;
alter table sla_trackers force row level security;
alter table worker_excuses force row level security;
alter table complaint_verification_actions force row level security;
alter table escalations force row level security;
alter table closure_verifications force row level security;
alter table citizen_verification_reminders force row level security;
alter table complaint_embeddings force row level security;
alter table master_issues force row level security;
alter table master_issue_members force row level security;
alter table worker_completion_features force row level security;
alter table anomaly_flags force row level security;
alter table photo_hash_registry force row level security;
alter table recurring_issue_patterns force row level security;
alter table push_subscriptions force row level security;
alter table notification_log force row level security;
