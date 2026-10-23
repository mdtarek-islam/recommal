"""Tests for the refined adult flag, the seeder flag, the patch-note cleaner and the recommendation filter."""

from __future__ import annotations

import re
from typing import Any

import pandas as pd
import pytest

from db.migrate_and_seed import GAME_COLUMNS, _item_rows, fixtures
from src.db import queries
from src.ingest.adult import adult_signals, is_adult_text, refine_adult
from src.ingest.clean import drop_patch_notes


def _items(rows: list[tuple[str, str, str, bool]]) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=["domain", "title", "synopsis", "is_adult"])


# --- refine_adult ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "title, synopsis",
    [
        ("Mommy Sensei: Horny Homework", "The naughty nurse is an absolute MILF."),
        ("Hentai Girls : Mommy Milkers", "A puzzle game."),
        ("Night Shift", "An NSFW visual novel."),
        ("Velvet Room", "Adults only. Contains sexual content and nudity."),
        ("Mommy's Milk and Cookies - Christmas Sex Puzzles", "Sexy Christmas puzzles."),
        ("Waifu Collector", "Collect every waifu. 18+ only."),
        ("Garden Story", "Uncensored edition with explicit scenes."),
    ],
)
def test_text_signals_flag_adult_games(title: str, synopsis: str) -> None:
    assert is_adult_text(f"{title}\n{synopsis}", "game")


@pytest.mark.parametrize(
    "title, synopsis",
    [
        ("Death Note", "A high school student finds a notebook that kills anyone whose name is written in it."),
        ("Hollow Knight", "Forge your own path in an insect kingdom. Version 1.5 adds new bosses."),
        ("Stardew Valley", "Inherit your grandfather's farm plot. Raise animals and find love."),
        ("Mommy's Little Helper", "A cooking game for the whole family."),
        ("Cozy Grove", "This game contains no nudity and no sexual content."),
        ("Harem Defence", "Defend the sultan's harem from invaders."),
        ("Year 2018", "Released in 2018 for players aged 12+."),
    ],
)
def test_text_signals_keep_safe_games(title: str, synopsis: str) -> None:
    assert not is_adult_text(f"{title}\n{synopsis}", "game"), adult_signals(f"{title}\n{synopsis}")


def test_one_weak_signal_never_flags_and_ecchi_needs_another_signal() -> None:
    assert not is_adult_text("Ecchi Puzzle\nSlide the tiles.", "game")
    assert is_adult_text("Ecchi Puzzle\nSlide the tiles to reveal busty girls.", "game")
    assert not is_adult_text("Sex Pistols Tribute\nA punk rhythm game.", "game")


def test_anime_needs_a_higher_score_than_games() -> None:
    text = "Comic Girls\nKaos lives with Ruki, who draws erotic manga."
    assert is_adult_text(text, "game")
    assert not is_adult_text(text, "anime")
    assert is_adult_text("Futari Ecchi\nA porn-free guide? No: an ecchi sex comedy.", "anime")


def test_refine_adult_keeps_existing_flags_and_index() -> None:
    items = _items([
        ("game", "Mommy Sensei: Horny Homework", "An absolute MILF.", False),
        ("game", "Flagged By Steam", "A quiet story.", True),
        ("anime", "Death Note", "A notebook that kills.", False),
    ]).set_axis([10, 20, 30])  # fmt: skip
    flags = refine_adult(items)
    assert flags.name == "is_adult" and flags.dtype == bool
    assert flags.to_dict() == {10: True, 20: True, 30: False}


def test_refine_adult_handles_missing_columns_and_values() -> None:
    items = pd.DataFrame({"title": ["Hentai Pool", None], "synopsis": [None, None]})
    assert refine_adult(items).tolist() == [True, False]


# --- seeder ---------------------------------------------------------------------------------------


def test_item_rows_seed_the_refined_flag_and_drop_patch_notes() -> None:
    items, _ = fixtures(n_per_domain=5)
    game = items.index[items["domain"] == "game"][0]
    items.loc[game, ["title", "synopsis"]] = [
        "Mommy Sensei: Horny Homework",
        "Story first.\nPatch Notes\n- Fixed a crash.\n- Added a mode.\nFeatures last.",
    ]
    rows = {row[0]: row for row in _item_rows(items, "game")}
    row = rows[int(items.loc[game, "item_id"])]
    assert row[GAME_COLUMNS.index("is_adult")] is True
    assert row[GAME_COLUMNS.index("synopsis")] == "Story first.\nFeatures last."
    assert sum(r[GAME_COLUMNS.index("is_adult")] for r in rows.values()) == 1


# --- drop_patch_notes -----------------------------------------------------------------------------


def test_drop_patch_notes_removes_changelog_blocks() -> None:
    text = "\n".join([
        "Build a city in the clouds.",
        "v1.2.3",
        "- Fixed save corruption.",
        "- Added a photo mode.",
        "Update 4: the winter festival",
        "[Gameplay] Fixed wind direction.",
        "Hotfix:",
        "Fixed a crash on start.",
        "Explore twenty islands.",
        "Changelog",
        "Improved shadows.",
    ])  # fmt: skip
    assert drop_patch_notes(text) == "Build a city in the clouds.\nExplore twenty islands."


def test_drop_patch_notes_keeps_feature_text() -> None:
    text = "\n".join([
        "Forge your own path.",
        "Godmaster",
        "- Take your place amongst the Gods. New Boss Fights.",
        "PC Settings/Optimizations",
        "Updates will be released regularly.",
        "Added bonus: a free soundtrack.",
        "Patch Play is a mini-game about quilts.",
    ])  # fmt: skip
    assert drop_patch_notes(text) == text


def test_drop_patch_notes_never_removes_the_first_line() -> None:
    assert drop_patch_notes("Version 1.0.2\nFixed a crash.\nAdded a mode.") == "Version 1.0.2"
    assert drop_patch_notes("Patch 3") == "Patch 3"
    assert drop_patch_notes("") == ""


# --- get_recommendations --------------------------------------------------------------------------


def _capture(monkeypatch: pytest.MonkeyPatch, rows: list[dict[str, Any]]) -> dict[str, Any]:
    captured: dict[str, Any] = {}

    def fake_fetch_all(sql: str, params: Any) -> list[dict[str, Any]]:
        captured["sql"], captured["params"] = " ".join(sql.split()), params
        return rows

    monkeypatch.setattr(queries, "fetch_all", fake_fetch_all)
    return captured


@pytest.mark.parametrize(
    ("domain", "source", "target"),
    [("anime", "public.animes", "public.steam_games"), ("game", "public.steam_games", "public.animes")],
)
def test_get_recommendations_filters_adult_targets_for_non_adult_sources(
    monkeypatch: pytest.MonkeyPatch, domain: str, source: str, target: str
) -> None:
    captured = _capture(monkeypatch, [])
    assert queries.get_recommendations(domain, 42, "control") == []
    sql = captured["sql"]
    assert f"join {target} t on t.id = u.target_id" in sql
    # A left join keeps the query valid when the source row is missing; coalesce treats it as non-adult.
    assert f"left join {source} s on s.id = r.source_id" in sql
    assert "(coalesce(s.is_adult, false) or not t.is_adult)" in sql
    assert sql.endswith("order by u.rank")
    assert captured["params"] == ("control", domain, 42)
    assert not re.search(r"limit\s+\d", sql)


def test_get_recommendations_returns_fewer_rows_in_rank_order(monkeypatch: pytest.MonkeyPatch) -> None:
    rows = [{"rank": 1, "id": 7, "title": "A"}, {"rank": 4, "id": 9, "title": "B"}]
    _capture(monkeypatch, rows)
    assert [r["rank"] for r in queries.get_recommendations("anime", 1, "control")] == [1, 4]
