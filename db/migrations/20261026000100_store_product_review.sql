-- Products carry a reviewed state, separate from published, for checking the
-- catalog item by item before go-live. NULL means nobody has signed it off;
-- the admin sets it from the review queue or a product's visibility card.
alter table store.products add column reviewed_at timestamptz;

update store.schema_metadata set version = 5, applied_at = now();
