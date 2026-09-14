-- ============================================================
-- 011: Web Push Subscriptions + Notification Log
-- Depends on: 000, 003 (citizens/complaints), 004 (workers), 005 (worker_assignments)
-- ============================================================

create table push_subscriptions (
  id          uuid primary key default gen_random_uuid(),
  citizen_id  uuid references citizens(id) on delete cascade,
  worker_id   uuid references workers(id) on delete cascade,
  endpoint    text not null unique,
  p256dh      text not null,
  auth_key    text not null,
  user_agent  text,
  created_at  timestamptz not null default now(),

  constraint chk_push_subscription_owner check (
    (citizen_id is not null and worker_id is null) or
    (citizen_id is null and worker_id is not null)
  )
);

create index idx_push_subscriptions_citizen on push_subscriptions (citizen_id);
create index idx_push_subscriptions_worker on push_subscriptions (worker_id);

create table notification_log (
  id                            uuid primary key default gen_random_uuid(),
  push_subscription_id         uuid references push_subscriptions(id) on delete set null,
  notification_type            notification_type not null,
  related_complaint_id         uuid references complaints(id) on delete set null,
  related_worker_assignment_id uuid references worker_assignments(id) on delete set null,
  payload                      jsonb not null default '{}'::jsonb,
  sent_at                       timestamptz not null default now(),
  delivered                     boolean
);

create index idx_notification_log_type on notification_log (notification_type, sent_at);
create index idx_notification_log_complaint on notification_log (related_complaint_id);
