-- Variants cannot be deleted, so they are retired by unpublishing them. An
-- unpublished variant is hidden from the store and cannot be bought, but stays
-- on the orders that already sold it.
alter table store.variants add column published boolean not null default true;

-- Orders placed before 20261020000000 have no variant_id; every later order
-- item names the variant it sold, which can never be deleted while it does.
alter table store.order_items
    add constraint order_items_variant_id_fkey
    foreign key (variant_id) references store.variants(id) on delete restrict;

update store.schema_metadata set version = 3, applied_at = now();
