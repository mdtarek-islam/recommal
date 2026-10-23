-- 002_security_hardening.sql
-- Close default grants, restrict image URLs to HTTPS and add a server-side login throttle.
-- Idempotent: safe to run more than once. Never edit this file after a database applies it.

-- --------------------------------------------------- default privileges
-- Supabase grants ALL on new public objects to anon and authenticated by default.
-- Revoke those defaults so each future table, sequence or function starts closed.
-- The defaults owned by supabase_admin are outside the reach of the postgres role.
do $$
begin
    if not exists (select 1 from pg_roles where rolname = 'anon') then
        return;  -- Plain PostgreSQL (tests, local): no Supabase API roles exist.
    end if;

    alter default privileges in schema public revoke all on tables    from anon, authenticated;
    alter default privileges in schema public revoke all on sequences from anon, authenticated;
    alter default privileges in schema public revoke all on functions from anon, authenticated;

    -- Nested checks: SQL does not guarantee left-to-right evaluation of AND.
    if exists (select 1 from pg_roles where rolname = 'postgres') then
    if pg_has_role(current_user, 'postgres', 'MEMBER') then
        alter default privileges for role postgres in schema public revoke all on tables    from anon, authenticated;
        alter default privileges for role postgres in schema public revoke all on sequences from anon, authenticated;
        alter default privileges for role postgres in schema public revoke all on functions from anon, authenticated;
        -- PostgreSQL grants EXECUTE to PUBLIC on every new function. Only a global revoke removes it.
        alter default privileges for role postgres revoke execute on functions from public;
    end if;
    end if;

    -- Existing objects. Migration 002 found no functions in public; this covers any added later by hand.
    revoke execute on all functions in schema public from anon, authenticated;
    revoke all on all sequences in schema public from anon, authenticated;
end $$;

-- ------------------------------------------------------ HTTPS image URLs
-- The app renders image_url in the browser. Allow NULL or an https:// URL only.
-- Both tables are empty when this migration first runs, so validation is instant.
do $$
begin
    if not exists (select 1 from pg_constraint where conname = 'animes_image_url_https'
                   and conrelid = 'public.animes'::regclass) then
        alter table public.animes add constraint animes_image_url_https
            check (image_url is null or image_url ~ '^https://');
    end if;
    if not exists (select 1 from pg_constraint where conname = 'steam_games_image_url_https'
                   and conrelid = 'public.steam_games'::regclass) then
        alter table public.steam_games add constraint steam_games_image_url_https
            check (image_url is null or image_url ~ '^https://');
    end if;
end $$;

-- -------------------------------------------------------- login throttle
-- One row per login attempt. email_hash is a salted SHA-256 pseudonym; no email is stored.
-- Retention: auth_utils deletes rows older than 1 day each time it records an attempt.
-- To prune by hand, run: delete from public.login_attempts where attempted_at < now() - interval '1 day';
create table if not exists public.login_attempts (
    id            bigint generated always as identity primary key,
    email_hash    text        not null,
    attempted_at  timestamptz not null default now(),
    succeeded     boolean     not null
);
-- Serves the throttle count: equality on email_hash, range on attempted_at.
create index if not exists login_attempts_email_time
    on public.login_attempts (email_hash, attempted_at desc);
-- Serves the retention delete. BRIN suits an append-only time column and stays a few pages in size.
create index if not exists login_attempts_time_brin
    on public.login_attempts using brin (attempted_at);

alter table public.login_attempts enable row level security;
-- No policies: the REST API cannot read or write login attempts.

do $$
begin
    if exists (select 1 from pg_roles where rolname = 'anon') then
        revoke all on public.login_attempts from anon, authenticated;
        revoke all on all sequences in schema public from anon, authenticated;
    end if;
end $$;
