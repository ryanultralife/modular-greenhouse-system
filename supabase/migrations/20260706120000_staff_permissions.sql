-- Per-staff grantable admin areas. A JSON array of area keys (subset of
-- STAFF_PERMISSIONS in api/models_db.py, e.g. ["orders","catalog"]).
-- Checked live on every request, so revoking is immediate.
alter table users
  add column if not exists permissions jsonb not null default '[]'::jsonb;
