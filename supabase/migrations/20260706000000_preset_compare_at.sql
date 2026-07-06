-- Promo support: optional regular ("compare at") price on presets, shown as a
-- strikethrough next to the sale price on the public site.
-- Idempotent; mirrors api/models_db.py.

alter table presets add column if not exists compare_at_usd double precision;
