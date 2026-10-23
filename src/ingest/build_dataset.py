"""Build the cleaned cross-domain item table from the MyAnimeList and Steam dumps.

Run: python -m src.ingest.build_dataset
Output: data/processed/items.parquet (one row per anime or game).
"""

from __future__ import annotations

import logging
import re
from collections import defaultdict
from pathlib import Path

import pandas as pd

from src.config import SETTINGS
from src.ingest.clean import NO_SYNOPSIS, clean_synopsis, merge_descriptions, normalise_title, truncate
from src.ingest.pgdump import iter_copy_tables
from src.ingest.themes import (
    ADULT_ANIME_GENRES,
    ADULT_STEAM_GENRES,
    NON_GAME_STEAM_GENRES,
    anime_themes,
    game_themes,
)

log = logging.getLogger(__name__)

EXCLUDED_ANIME_MEDIA = frozenset({"music", "pv", "cm"})
ADULT_ANIME_RATINGS = frozenset({"rx"})
_YEAR_RE = re.compile(r"(19|20)\d{2}")

ITEM_COLUMNS = [
    "domain", "item_id", "title", "alt_title", "synopsis", "model_text", "image_url", "year",
    "popularity", "is_adult", "genres", "themes", "external_id",
]  # fmt: skip


def _int(value: str | None) -> int | None:
    try:
        return int(value) if value not in (None, "") else None
    except ValueError:
        return None


def _year(value: str | None) -> int | None:
    match = _YEAR_RE.search(value or "")
    return int(match.group(0)) if match else None


def _model_text(title: str, synopsis: str) -> str:
    """Return the SBERT input. Use title and synopsis only; genre labels are the ground truth."""
    body = "" if synopsis == NO_SYNOPSIS else synopsis.replace("\n", " ")
    return truncate(f"{title}. {body}".strip(), SETTINGS.text.max_model_chars)


def build_anime(dump: Path) -> pd.DataFrame:
    tables = ("anime_genres", "anime_main_pictures", "anime_titles", "animes", "genres")
    genre_names: dict[int, str] = {}
    item_genres: dict[int, list[int]] = defaultdict(list)
    pictures: dict[int, str] = {}
    english: dict[int, str] = {}
    animes: list[dict[str, str | None]] = []
    for table, row in iter_copy_tables(dump, tables):
        if table == "genres":
            genre_names[int(row["id"] or 0)] = row["name"] or ""
        elif table == "anime_genres":
            item_genres[int(row["anime_id"] or 0)].append(int(row["genre_id"] or 0))
        elif table == "anime_main_pictures":
            pictures[int(row["anime_id"] or 0)] = row["large_url"] or row["medium_url"] or ""
        elif table == "anime_titles" and row.get("en"):
            english[int(row["anime_id"] or 0)] = row["en"] or ""
        elif table == "animes":
            animes.append(row)

    records = []
    for row in animes:
        anime_id = int(row["id"] or 0)
        if (row.get("media_type") or "") in EXCLUDED_ANIME_MEDIA:
            continue
        synopsis = clean_synopsis(row.get("synopsis"))
        if synopsis == NO_SYNOPSIS:
            continue
        title = (row.get("title") or "").strip()
        genres = sorted({genre_names.get(g, "") for g in item_genres.get(anime_id, [])} - {""})
        records.append({
            "domain": "anime",
            "item_id": anime_id,
            "title": title,
            "alt_title": english.get(anime_id) or None,
            "synopsis": synopsis,
            "model_text": _model_text(title, synopsis),
            "image_url": pictures.get(anime_id) or None,
            "year": _year(row.get("start_date")),
            "popularity": _int(row.get("num_list_users")) or 0,
            "is_adult": (row.get("rating") in ADULT_ANIME_RATINGS) or bool(ADULT_ANIME_GENRES & set(genres)),
            "genres": genres,
            "themes": anime_themes(genres),
            "external_id": anime_id,
        })  # fmt: skip
    return pd.DataFrame.from_records(records, columns=ITEM_COLUMNS)


def build_games(dump: Path) -> pd.DataFrame:
    tables = ("game_genres", "games", "genres", "recommendations", "release_dates")
    genre_names: dict[int, str] = {}
    item_genres: dict[int, list[int]] = defaultdict(list)
    review_totals: dict[int, int] = {}
    release_years: dict[int, int | None] = {}
    games: list[dict[str, object]] = []
    for table, row in iter_copy_tables(dump, tables):
        if table == "genres":
            genre_names[int(row["id"] or 0)] = row["description"] or ""
        elif table == "game_genres":
            item_genres[int(row["game_id"] or 0)].append(int(row["genre_id"] or 0))
        elif table == "recommendations":
            review_totals[int(row["id"] or 0)] = _int(row["total"]) or 0
        elif table == "release_dates":
            release_years[int(row["id"] or 0)] = _year(row["date_raw"])
        elif table == "games" and row.get("type") == "game":
            # Clean now so that the raw HTML does not stay in memory.
            games.append({
                "id": int(row["id"] or 0),
                "name": (row.get("name") or "").strip(),
                "appid": _int(row.get("steam_appid")),
                "text": merge_descriptions(row.get("short_description"), row.get("about_the_game"),
                                           row.get("detailed_description")),
                "image": row.get("header_image"),
                "rec_id": _int(row.get("recommendations_id")),
                "date_id": _int(row.get("release_date_id")),
            })  # fmt: skip

    records = []
    for game in games:
        game_id = int(game["id"])  # type: ignore[call-overload]
        genres = sorted({genre_names.get(g, "") for g in item_genres.get(game_id, [])} - {""})
        if genres and set(genres) <= NON_GAME_STEAM_GENRES:
            continue
        synopsis = str(game["text"])
        title = str(game["name"])
        if synopsis == NO_SYNOPSIS or not title:
            continue
        rec_id, date_id = game["rec_id"], game["date_id"]
        records.append({
            "domain": "game",
            "item_id": game_id,
            "title": title,
            "alt_title": None,
            "synopsis": synopsis,
            "model_text": _model_text(title, synopsis),
            "image_url": game["image"] or None,
            "year": release_years.get(date_id) if isinstance(date_id, int) else None,
            "popularity": review_totals.get(rec_id, 0) if isinstance(rec_id, int) else 0,
            "is_adult": bool(ADULT_STEAM_GENRES & set(genres)),
            "genres": genres,
            "themes": game_themes(genres, f"{title}\n{synopsis}"),
            "external_id": game["appid"],
        })  # fmt: skip
    return pd.DataFrame.from_records(records, columns=ITEM_COLUMNS)


def deduplicate(items: pd.DataFrame) -> pd.DataFrame:
    """Keep the most popular row for each (domain, normalised title, synopsis prefix)."""
    key = items["title"].map(normalise_title) + "|" + items["synopsis"].str[:200].str.casefold()
    items = items.assign(_key=key).sort_values("popularity", ascending=False)
    items = items.drop_duplicates(subset=["domain", "_key"]).drop(columns="_key")
    return items.sort_values(["domain", "item_id"]).reset_index(drop=True)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    paths = SETTINGS.paths
    for dump in (paths.anime_dump, paths.steam_dump):
        if not dump.exists():
            raise SystemExit(f"Missing dump: {dump}. Set RECOMMAL_RAW_DIR to the folder that holds sql/.")
    log.info("Parsing anime dump %s", paths.anime_dump)
    anime = build_anime(paths.anime_dump)
    log.info("Parsing Steam dump %s", paths.steam_dump)
    games = build_games(paths.steam_dump)
    items = deduplicate(pd.concat([anime, games], ignore_index=True))
    paths.processed_dir.mkdir(parents=True, exist_ok=True)
    items.to_parquet(paths.items, index=False)
    counts = items["domain"].value_counts().to_dict()
    themed = items[items["themes"].map(len) > 0]["domain"].value_counts().to_dict()
    log.info("Wrote %s rows to %s: %s (with themes: %s)", len(items), paths.items, counts, themed)


if __name__ == "__main__":
    main()
