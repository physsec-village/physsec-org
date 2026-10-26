-- The store admin edits the whole catalog: collections and their groups, the
-- products in them, and product images. Collections get the same stale-form
-- protection products have, and the application role may delete catalog rows
-- that carry no history. Orders and checkouts still reference variants with
-- ON DELETE RESTRICT, so a variant that was ever reserved or sold (and the
-- product that owns it) cannot be deleted; the admin unpublishes those.
alter table store.collections
    add column updated_at timestamptz not null default now();

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
    execute format(
        'grant delete on store.products, store.variants, store.product_images, '
        'store.collections, store.collection_groups to %I',
        app_role
    );
end
$$;

update store.schema_metadata set version = 4, applied_at = now();
