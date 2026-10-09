create schema if not exists store;

revoke all on schema store from public;
do $$
begin
    if exists (select 1 from pg_roles where rolname = 'anon') then
        execute 'revoke all on schema store from anon';
    end if;
    if exists (select 1 from pg_roles where rolname = 'authenticated') then
        execute 'revoke all on schema store from authenticated';
    end if;
end
$$;

create table store.schema_metadata (
    singleton boolean primary key default true check (singleton),
    version integer not null,
    applied_at timestamptz not null default now()
);

insert into store.schema_metadata (version) values (1);

create table store.categories (
    code text primary key,
    label text not null
);

create table store.products (
    id bigint generated always as identity primary key,
    slug text unique not null,
    name text not null,
    base_sku text unique not null,
    description text not null default '',
    category_code text not null references store.categories(code),
    featured boolean not null default false,
    published boolean not null default true,
    created_at timestamptz not null,
    updated_at timestamptz not null
);

create table store.variants (
    id bigint generated always as identity primary key,
    product_id bigint not null references store.products(id) on delete restrict,
    sku text unique not null,
    upc text not null default '',
    name text not null default '',
    price_cents integer not null check (price_cents >= 0),
    stock_on_hand integer not null default 0 check (stock_on_hand >= 0),
    position integer not null default 0
);

create table store.product_images (
    id bigint generated always as identity primary key,
    product_id bigint not null references store.products(id) on delete cascade,
    filename text not null,
    alt text not null default '',
    position integer not null default 0
);

create table store.checkouts (
    id text primary key,
    status text not null check (
        status in ('creating', 'open', 'paid', 'expired', 'failed', 'canceled')
    ),
    stripe_session_id text unique,
    stripe_payment_intent_id text,
    currency text not null,
    subtotal_cents integer not null check (subtotal_cents >= 0),
    created_at timestamptz not null,
    expires_at timestamptz not null,
    completed_at timestamptz,
    failure_code text,
    version integer not null default 0
);

create table store.checkout_items (
    checkout_id text not null references store.checkouts(id) on delete restrict,
    variant_id bigint not null references store.variants(id) on delete restrict,
    sku text not null,
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

create table store.stripe_events (
    event_id text primary key,
    event_type text not null,
    stripe_object_id text,
    stripe_created_at bigint,
    payload_sha256 text,
    state text not null check (state in ('received', 'processed', 'ignored', 'failed')),
    attempts integer not null default 0,
    received_at timestamptz not null,
    processed_at timestamptz,
    last_error_code text,
    last_error_detail text
);

create table store.orders (
    id text primary key,
    checkout_id text unique not null references store.checkouts(id),
    stripe_session_id text unique not null,
    payment_intent_id text unique,
    email text,
    shipping_json jsonb,
    currency text not null,
    amount_subtotal_cents integer not null check (amount_subtotal_cents >= 0),
    amount_shipping_cents integer not null default 0 check (amount_shipping_cents >= 0),
    amount_tax_cents integer not null default 0 check (amount_tax_cents >= 0),
    amount_total_cents integer not null check (amount_total_cents >= 0),
    amount_refunded_cents integer not null default 0 check (
        amount_refunded_cents >= 0 and amount_refunded_cents <= amount_total_cents
    ),
    payment_state text not null check (
        payment_state in ('pending', 'paid', 'failed', 'canceled')
    ),
    fulfillment_state text not null check (
        fulfillment_state in ('unfulfilled', 'processing', 'shipped', 'canceled')
    ),
    review_state text not null check (review_state in ('clear', 'needs_review')),
    review_reason text,
    refund_state text not null check (refund_state in ('none', 'partial', 'full')),
    created_at timestamptz not null,
    paid_at timestamptz,
    updated_at timestamptz not null
);

create table store.order_items (
    id bigint generated always as identity primary key,
    order_id text not null references store.orders(id) on delete restrict,
    sku text not null,
    product_name text not null,
    variant_name text not null default '',
    quantity integer not null check (quantity > 0),
    unit_amount_cents integer not null check (unit_amount_cents >= 0)
);

create index idx_products_public on store.products(published, featured);
create index idx_variants_product on store.variants(product_id, position);
create index idx_images_product on store.product_images(product_id, position);
create index idx_reservations_active
    on store.inventory_reservations(variant_id, expires_at)
    where state = 'active';
create index idx_checkouts_expiry on store.checkouts(status, expires_at);
create index idx_orders_payment_intent on store.orders(payment_intent_id);
create index idx_order_items_order on store.order_items(order_id);

-- Migrations run as the project owner. The application uses this restricted
-- role after an administrator enables LOGIN and assigns a generated password.
do $$
begin
    if not exists (select 1 from pg_roles where rolname = 'store_app') then
        create role store_app nologin nosuperuser nocreatedb nocreaterole noinherit;
    end if;
end
$$;

grant usage on schema store to store_app;
grant select, insert, update on all tables in schema store to store_app;
revoke insert, update on store.schema_metadata from store_app;
grant usage, select on all sequences in schema store to store_app;
alter default privileges in schema store
    grant select, insert, update on tables to store_app;
alter default privileges in schema store
    grant usage, select on sequences to store_app;
