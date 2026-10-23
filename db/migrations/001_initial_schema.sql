-- 001_initial_schema.sql
-- Recommal schema for Supabase PostgreSQL (free tier).
-- Idempotent: safe to run more than once.
-- Security model: the Streamlit server connects as the database owner over the pooler.
-- Row-Level Security is on for every table, so the public REST API (anon and
-- authenticated keys) cannot read password hashes or telemetry. Catalogue tables
-- allow read-only access through explicit policies.

-- Supabase creates the extensions schema. Plain PostgreSQL (tests, local) may not have it.
create schema if not exists extensions;
create extension if not exists pg_trgm with schema extensions;

-- ---------------------------------------------------------------- catalogue
create table if not exists public.animes (
    id           integer primary key,
    title        text not null,
    alt_title    text,
    synopsis     text not null,
    image_url    text,
    start_year   smallint,
    popularity   integer not null default 0 check (popularity >= 0),
    is_adult     boolean not null default false,
    genres       text[] not null default '{}',
    themes       text[] not null default '{}'
);

create table if not exists public.steam_games (
    id           integer primary key,
    steam_appid  integer unique,
    title        text not null,
    synopsis     text not null,
    image_url    text,
    release_year smallint,
    popularity   integer not null default 0 check (popularity >= 0),
    is_adult     boolean not null default false,
    genres       text[] not null default '{}',
    themes       text[] not null default '{}'
);

-- Trigram indexes serve case-insensitive title search (ILIKE and similarity()).
create index if not exists animes_title_trgm on public.animes using gin (lower(title) extensions.gin_trgm_ops);
create index if not exists animes_alt_title_trgm on public.animes using gin (lower(alt_title) extensions.gin_trgm_ops);
create index if not exists steam_games_title_trgm on public.steam_games using gin (lower(title) extensions.gin_trgm_ops);
create index if not exists animes_popularity on public.animes (popularity desc);
create index if not exists steam_games_popularity on public.steam_games (popularity desc);

-- --------------------------------------------------------- recommendations
-- One row per (variant, source item). target_ids[k] is the item at rank k; scores[k] is its score.
-- The target domain is always the other domain. One row with arrays takes about a quarter of
-- the space of five rows of (rank, target_id, score), which keeps the free tier under 500 MB.
create table if not exists public.recommendations (
    variant        text      not null check (variant in ('control', 'explained')),
    source_domain  text      not null check (source_domain in ('anime', 'game')),
    source_id      integer   not null,
    target_ids     integer[] not null,
    scores         real[]    not null,
    model_version  text      not null,
    primary key (variant, source_domain, source_id),
    constraint recommendations_arrays_match check (
        array_ndims(target_ids) = 1 and cardinality(target_ids) between 1 and 20
        and cardinality(scores) = cardinality(target_ids)
        and array_position(target_ids, null) is null
    )
);
-- The primary key serves the lookup (variant, source_domain, source_id).
-- target_ids has no foreign key: an element points to animes or steam_games, chosen by domain.
-- db/migrate_and_seed.py checks referential integrity before it commits each seed.

-- ------------------------------------------------------------------- users
create table if not exists public.users (
    id             bigint generated always as identity primary key,
    email          text not null,
    password_hash  text not null,
    created_at     timestamptz not null default now(),
    constraint users_email_format check (email ~* '^[^@\s]+@[^@\s]+\.[^@\s]+$')
);
create unique index if not exists users_email_lower_key on public.users (lower(email));

-- ------------------------------------------------------------ A/B telemetry
create table if not exists public.ab_test_events (
    id             bigint generated always as identity primary key,
    occurred_at    timestamptz not null default now(),
    experiment     text not null,
    variant        text not null,
    user_hash      text not null,
    event_type     text not null check (event_type in ('exposure', 'feedback', 'search')),
    query          text,
    source_domain  text check (source_domain in ('anime', 'game')),
    source_id      integer,
    rec_ids        integer[],
    target_id      integer,
    relevance      smallint check (relevance in (-1, 1)),
    metadata       jsonb not null default '{}'::jsonb
);
create index if not exists ab_test_events_analysis
    on public.ab_test_events (experiment, variant, event_type, occurred_at);

-- ------------------------------------------------------- row-level security
alter table public.animes          enable row level security;
alter table public.steam_games     enable row level security;
alter table public.recommendations enable row level security;
alter table public.users           enable row level security;
alter table public.ab_test_events  enable row level security;

drop policy if exists animes_public_read on public.animes;
create policy animes_public_read on public.animes for select to anon, authenticated using (true);
drop policy if exists steam_games_public_read on public.steam_games;
create policy steam_games_public_read on public.steam_games for select to anon, authenticated using (true);
drop policy if exists recommendations_public_read on public.recommendations;
create policy recommendations_public_read on public.recommendations
    for select to anon, authenticated using (true);
-- users and ab_test_events have no policies: the REST API cannot read or write them.

-- Supabase grants ALL on new public objects to anon and authenticated by default.
-- Revoke everything (TRUNCATE ignores RLS), then grant read access to the catalogue only.
revoke all on public.users, public.ab_test_events from anon, authenticated;
revoke all on public.animes, public.steam_games, public.recommendations from anon, authenticated;
revoke all on all sequences in schema public from anon, authenticated;
grant select on public.animes, public.steam_games, public.recommendations to anon, authenticated;
