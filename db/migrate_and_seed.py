"""Apply SQL migrations and seed the Supabase database.

Usage:
    python -m db.migrate_and_seed                # migrate, then seed from artefacts
    python -m db.migrate_and_seed --migrate-only
    python -m db.migrate_and_seed --fixtures     # seed deterministic development fixtures

Seeding replaces catalogue and recommendation rows in one transaction. It never touches
`users`, `ab_test_events` or `login_attempts`. Credentials come from src.db.pool.db_settings().
"""

from __future__ import annotations

import argparse
import csv
import io
import logging
import random
import sys
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import psycopg2
from psycopg2.extensions import connection as PgConnection

from src.config import SEED, SETTINGS
from src.db.pool import db_settings
from src.ingest.adult import refine_adult
from src.ingest.clean import NO_SYNOPSIS, clean_title, drop_patch_notes, https_image_url, strip_broken_chars, truncate
from src.ingest.themes import THEMES

log = logging.getLogger("recommal.migrate")

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"
FREE_TIER_BYTES = 500 * 1024 * 1024
BATCH_ROWS = 20_000

ANIME_COLUMNS = ("id", "title", "alt_title", "synopsis", "image_url", "start_year", "popularity", "is_adult",
                 "genres", "themes")  # fmt: skip
GAME_COLUMNS = ("id", "steam_appid", "title", "synopsis", "image_url", "release_year", "popularity", "is_adult",
                "genres", "themes")  # fmt: skip
# Long format written by the ML pipeline: one row per (variant, source item, rank).
REC_COLUMNS = ("variant", "source_domain", "source_id", "rank", "target_domain", "target_id", "score",
               "model_version")  # fmt: skip
# Stored format: one row per (variant, source item) with targets and scores ordered by rank.
REC_TABLE_COLUMNS = ("variant", "source_domain", "source_id", "target_ids", "scores", "model_version")


def connect() -> PgConnection:
    return psycopg2.connect(sslmode="require", connect_timeout=SETTINGS.database.connect_timeout_s,
                            application_name="recommal-migrate", **db_settings())  # fmt: skip


def pg_array(values: Iterable[Any]) -> str:
    """Return a PostgreSQL array literal with every element quoted. PostgreSQL casts it to the column type."""
    quoted = ('"' + str(v).replace("\\", "\\\\").replace('"', '\\"') + '"' for v in values)
    return "{" + ",".join(quoted) + "}"


def _csv_value(value: Any) -> Any:
    if isinstance(value, np.generic):  # NumPy scalars, including np.bool_, which also has tolist().
        value = value.item()
    if isinstance(value, (list, tuple, np.ndarray)):
        return pg_array(list(value))
    if value is None or pd.isna(value):
        return r"\N"
    if isinstance(value, bool):
        return "t" if value else "f"
    return value


def copy_rows(conn: PgConnection, table: str, columns: Sequence[str], rows: Iterable[Sequence[Any]]) -> int:
    """Stream rows into `table` with COPY in batches. Return the row count."""
    sql = f"copy {table} ({', '.join(columns)}) from stdin with (format csv, null '\\N')"
    total = 0
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    with conn.cursor() as cur:
        for row in rows:
            writer.writerow([_csv_value(v) for v in row])
            total += 1
            if total % BATCH_ROWS == 0:
                buffer.seek(0)
                cur.copy_expert(sql, buffer)
                buffer.seek(0)
                buffer.truncate()
        if buffer.tell():
            buffer.seek(0)
            cur.copy_expert(sql, buffer)
    return total


def migrate(conn: PgConnection) -> list[str]:
    """Apply each pending migration in file-name order, one transaction per file."""
    with conn, conn.cursor() as cur:
        cur.execute("create table if not exists public.schema_migrations "
                    "(version text primary key, applied_at timestamptz not null default now())")  # fmt: skip
        cur.execute("alter table public.schema_migrations enable row level security")
        cur.execute("do $$ begin if exists (select 1 from pg_roles where rolname = 'anon') then "
                    "revoke all on public.schema_migrations from anon, authenticated; end if; end $$")  # fmt: skip
        cur.execute("select version from public.schema_migrations")
        applied = {row[0] for row in cur.fetchall()}
    done = []
    for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
        if path.stem in applied:
            continue
        log.info("Applying %s", path.name)
        with conn, conn.cursor() as cur:
            cur.execute(path.read_text(encoding="utf-8"))
            cur.execute("insert into public.schema_migrations (version) values (%s)", (path.stem,))
        done.append(path.stem)
    return done


def _item_rows(items: pd.DataFrame, domain: str) -> Iterable[tuple[Any, ...]]:
    limit = SETTINGS.text.max_stored_chars
    subset = items[items["domain"] == domain]
    adult = refine_adult(subset)  # Seed the refined flag: source flag OR title and synopsis signals.
    for r, is_adult in zip(subset.itertuples(index=False), adult.to_numpy(), strict=True):
        year = None if pd.isna(r.year) else int(r.year)
        title = clean_title(r.title)
        if title is None:
            raise ValueError(f"Item {domain}:{r.item_id} has no title after cleaning.")
        synopsis = drop_patch_notes((strip_broken_chars(r.synopsis) or "").strip()).strip() or NO_SYNOPSIS
        common = (title, truncate(synopsis, limit), https_image_url(r.image_url), year, int(r.popularity),
                  bool(is_adult), list(r.genres), list(r.themes))  # fmt: skip
        if domain == "anime":
            yield (int(r.item_id), title, clean_title(r.alt_title), *common[1:])
        else:
            appid = None if pd.isna(r.external_id) else int(r.external_id)
            yield (int(r.item_id), appid, *common)


# recommendations.target_id cannot carry one foreign key across two tables, so seed() checks it.
ORPHAN_SQL = """
    select count(*)
    from public.recommendations r
    cross join lateral unnest(r.target_ids) as t(target_id)
    left join public.animes a
           on a.id = case when r.source_domain = 'anime' then r.source_id else t.target_id end
    left join public.steam_games g
           on g.id = case when r.source_domain = 'game' then r.source_id else t.target_id end
    where a.id is null or g.id is null
"""


def _rec_rows(recs: pd.DataFrame) -> Iterable[tuple[Any, ...]]:
    """Group long-format recommendations into one row per (variant, source item), ordered by rank."""
    if (recs["source_domain"] == recs["target_domain"]).any():
        raise ValueError("A recommendation targets its own domain.")
    if recs.duplicated(["variant", "source_domain", "source_id", "rank"]).any():
        raise ValueError("Duplicate (variant, source_domain, source_id, rank) in recommendations.")
    ordered = recs.sort_values(["variant", "source_domain", "source_id", "rank"], kind="stable")
    for (variant, domain, source_id), group in ordered.groupby(["variant", "source_domain", "source_id"],
                                                                sort=False):  # fmt: skip
        yield (variant, domain, int(source_id), [int(t) for t in group["target_id"]],
               [float(x) for x in group["score"]], str(group["model_version"].iloc[0]))  # fmt: skip


def seed(conn: PgConnection, items: pd.DataFrame, recs: pd.DataFrame) -> dict[str, int]:
    """Replace catalogue and recommendation rows in one transaction."""
    with conn, conn.cursor() as cur:
        cur.execute("truncate public.recommendations, public.animes, public.steam_games")
        counts = {
            "animes": copy_rows(conn, "public.animes", ANIME_COLUMNS, _item_rows(items, "anime")),
            "steam_games": copy_rows(conn, "public.steam_games", GAME_COLUMNS, _item_rows(items, "game")),
            "recommendations": copy_rows(conn, "public.recommendations", REC_TABLE_COLUMNS,
                                         _rec_rows(recs)),
        }  # fmt: skip
        cur.execute(ORPHAN_SQL)
        orphans = int(cur.fetchone()[0])
        if orphans:  # An exception inside `with conn` rolls the whole seed back.
            raise ValueError(f"{orphans} recommendation targets reference a missing source or target item.")
    with conn, conn.cursor() as cur:
        cur.execute("analyze public.animes, public.steam_games, public.recommendations")
    return counts


def fixtures(n_per_domain: int = 50, seed_value: int = SEED) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return deterministic development items and recommendations for both A/B variants."""
    rng = random.Random(seed_value)
    rows = []
    for domain in ("anime", "game"):
        for i in range(1, n_per_domain + 1):
            themes = sorted(rng.sample(THEMES, k=rng.randint(1, 3)))
            rows.append({
                "domain": domain, "item_id": i, "title": f"Fixture {domain.title()} {i:03d}", "alt_title": None,
                "synopsis": f"A development fixture about {', '.join(themes)}.", "image_url": None,
                "year": 2000 + i % 25, "popularity": rng.randint(0, 100_000), "is_adult": False,
                "genres": [], "themes": themes, "external_id": 100_000 + i,
            })  # fmt: skip
    items = pd.DataFrame(rows)
    recs = []
    for variant in ("control", "explained"):
        for domain, other in (("anime", "game"), ("game", "anime")):
            for i in range(1, n_per_domain + 1):
                targets = rng.sample(range(1, n_per_domain + 1), 5)
                for rank, target in enumerate(targets, start=1):
                    recs.append((variant, domain, i, rank, other, target, round(1 - rank * 0.1, 3), "fixtures"))
    return items, pd.DataFrame(recs, columns=list(REC_COLUMNS))


def database_size(conn: PgConnection) -> int:
    with conn.cursor() as cur:
        cur.execute("select pg_database_size(current_database())")
        return int(cur.fetchone()[0])


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--migrate-only", action="store_true")
    mode.add_argument("--fixtures", action="store_true")
    args = parser.parse_args(argv)

    conn = connect()
    try:
        applied = migrate(conn)
        log.info("Migrations applied: %s", applied or "none pending")
        if args.migrate_only:
            return 0
        if args.fixtures:
            items, recs = fixtures()
        else:
            paths = SETTINGS.paths
            missing = [p for p in (paths.items, paths.recommendations) if not p.exists()]
            if missing:
                log.error("Missing artefacts %s. Run the ML pipeline or use --fixtures.", missing)
                return 1
            items, recs = pd.read_parquet(paths.items), pd.read_parquet(paths.recommendations)
        counts = seed(conn, items, recs)
        size = database_size(conn)
        log.info("Seeded %s. Database size: %.1f MB of %d MB free tier.", counts, size / 2**20,
                 FREE_TIER_BYTES // 2**20)  # fmt: skip
        if size > 0.9 * FREE_TIER_BYTES:
            log.warning("Database is above 90%% of the free-tier limit.")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
