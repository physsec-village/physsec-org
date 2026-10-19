-- The first migration grants a fixed `store_app` role, but each environment
-- has its own application role (dev uses `store_dev_app`). The runner passes
-- the role named by DATABASE_URL in psv.app_role; grant it the same
-- privileges. For production's `store_app` this changes nothing.
do $$
declare
    app_role text := current_setting('psv.app_role', true);
begin
    if app_role is null or app_role = '' then
        raise exception 'psv.app_role is not set; apply migrations with python -m src.store.migrate';
    end if;
    -- Local and test databases may use the owner for both URLs. Never revoke
    -- the owner's own privileges on schema_metadata.
    if app_role = current_user then
        return;
    end if;
    -- Infrastructure provisions the role with its password and limits.
    if not exists (select 1 from pg_roles where rolname = app_role) then
        raise exception 'application role % does not exist', app_role;
    end if;

    execute format('grant usage on schema store to %I', app_role);
    execute format('grant select, insert, update on all tables in schema store to %I', app_role);
    execute format('revoke insert, update on store.schema_metadata from %I', app_role);
    execute format('grant usage, select on all sequences in schema store to %I', app_role);
    execute format(
        'alter default privileges in schema store grant select, insert, update on tables to %I',
        app_role
    );
    execute format(
        'alter default privileges in schema store grant usage, select on sequences to %I',
        app_role
    );
end
$$;
