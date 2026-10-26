-- We no longer carry the Adams-Rite Commercial Door Hook. It never sold or
-- was reserved, so its rows and photo can go rather than being unpublished.
delete from store.collection_items
    where product_id in (select id from store.products where slug = 'adams-rite-commercial-door-hook');
delete from store.product_images
    where product_id in (select id from store.products where slug = 'adams-rite-commercial-door-hook');
delete from store.variants
    where product_id in (select id from store.products where slug = 'adams-rite-commercial-door-hook');
delete from store.products where slug = 'adams-rite-commercial-door-hook';
