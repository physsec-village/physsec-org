-- Replace the SKU-derived catalog with explicit collections, products and
-- variants. A SKU is now only an optional inventory identifier: nothing about a
-- product's grouping or collection is read from it.
--
-- The old catalog tables are dropped rather than converted. Orders are kept:
-- order_items snapshot the SKU, names and prices, so they do not need the old
-- variants, and their variant_id stays NULL. Unpaid checkouts and their
-- reservations are discarded; paid ones stay because orders reference them.
drop table store.inventory_reservations;
drop table store.checkout_items;
delete from store.checkouts c
where not exists (select 1 from store.orders o where o.checkout_id = c.id);
drop table store.product_images;
drop table store.variants;
drop table store.products;
drop table store.categories;

update store.schema_metadata set version = 2, applied_at = now();

create table store.products (
    id bigint generated always as identity primary key,
    slug text unique not null check (slug ~ '^[a-z0-9]+(-[a-z0-9]+)*$'),
    name text not null check (name <> ''),
    description text not null default '',
    -- Short lines shown as a list on the product page (set contents, features).
    features text[] not null default '{}',
    featured boolean not null default false,
    published boolean not null default true,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create table store.variants (
    id bigint generated always as identity primary key,
    product_id bigint not null references store.products(id) on delete restrict,
    -- Empty for single-variant products; otherwise the option label shown to
    -- buyers (for example "Blue").
    name text not null default '',
    sku text unique check (sku is null or (sku <> '' and sku = btrim(sku))),
    upc text check (upc is null or upc <> ''),
    price_cents integer not null check (price_cents >= 0),
    stock_on_hand integer not null default 0 check (stock_on_hand >= 0),
    position integer not null default 0
);

create table store.product_images (
    id bigint generated always as identity primary key,
    product_id bigint not null references store.products(id) on delete cascade,
    url text not null check (url <> ''),
    alt text not null default '',
    position integer not null default 0
);

create table store.collections (
    id bigint generated always as identity primary key,
    slug text unique not null check (slug ~ '^[a-z0-9]+(-[a-z0-9]+)*$'),
    title text not null check (title <> ''),
    tag text not null default '',
    blurb text not null default '',
    -- Paragraphs separated by blank lines, shown above the collection's items.
    description text not null default '',
    position integer not null default 0,
    published boolean not null default true
);

-- Headed runs of products within a collection. A collection without headings
-- has a single group with an empty title.
create table store.collection_groups (
    id bigint generated always as identity primary key,
    collection_id bigint not null references store.collections(id) on delete cascade,
    title text not null default '',
    tag text not null default '',
    lede text not null default '',
    position integer not null default 0
);

-- A product may appear in any number of groups and collections.
create table store.collection_items (
    group_id bigint not null references store.collection_groups(id) on delete cascade,
    product_id bigint not null references store.products(id) on delete cascade,
    position integer not null default 0,
    primary key (group_id, product_id)
);

create table store.checkout_items (
    checkout_id text not null references store.checkouts(id) on delete restrict,
    variant_id bigint not null references store.variants(id) on delete restrict,
    sku text,
    product_name text not null,
    variant_name text not null default '',
    unit_amount_cents integer not null check (unit_amount_cents >= 0),
    quantity integer not null check (quantity > 0),
    primary key (checkout_id, variant_id)
);

create table store.inventory_reservations (
    id bigint generated always as identity primary key,
    checkout_id text not null references store.checkouts(id) on delete restrict,
    variant_id bigint not null references store.variants(id) on delete restrict,
    quantity integer not null check (quantity > 0),
    state text not null check (state in ('active', 'consumed', 'released')),
    expires_at timestamptz not null,
    created_at timestamptz not null,
    finalized_at timestamptz,
    unique (checkout_id, variant_id)
);

alter table store.order_items alter column sku drop not null;
alter table store.order_items add column variant_id bigint;

create index idx_products_public on store.products(published, featured);
create index idx_variants_product on store.variants(product_id, position);
create index idx_images_product on store.product_images(product_id, position);
create index idx_collection_groups on store.collection_groups(collection_id, position);
create index idx_collection_items_product on store.collection_items(product_id);
create index idx_reservations_active
    on store.inventory_reservations(variant_id, expires_at)
    where state = 'active';

-- 20261019000000 set default privileges, so the application role named by
-- psv.app_role already has select, insert and update on the new tables. The
-- admin UI also removes products from collections.
do $$
declare
    app_role text := current_setting('psv.app_role', true);
begin
    if app_role is null or app_role = '' then
        raise exception 'psv.app_role is not set; apply migrations with python -m src.store.migrate';
    end if;
    if app_role = current_user then
        return;
    end if;
    execute format('grant delete on store.collection_items to %I', app_role);
end
$$;
