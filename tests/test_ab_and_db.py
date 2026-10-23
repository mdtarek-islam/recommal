from collections import Counter
from typing import Any

import pytest

from db.migrate_and_seed import _item_rows, fixtures, pg_array
from src.ab_testing import events
from src.ab_testing.cohort import assign_variant, hash_user
from src.config import AB_VARIANTS
from src.db import pool, queries
from src.ingest.pgdump import decode_field
from src.ingest.themes import anime_themes, game_themes, jaccard


def test_assign_variant_is_stable_and_case_insensitive() -> None:
    assert assign_variant("User@Example.com") == assign_variant("user@example.com ")


def test_assign_variant_is_balanced() -> None:
    counts = Counter(assign_variant(f"user{i}@example.com") for i in range(4000))
    assert set(counts) == set(AB_VARIANTS)
    assert all(abs(c / 4000 - 1 / len(AB_VARIANTS)) < 0.03 for c in counts.values())


def test_hash_user_hides_the_email() -> None:
    digest = hash_user("person@example.com")
    assert "person" not in digest and len(digest) == 64


def test_build_event_contains_no_email() -> None:
    event = events.build_event("person@example.com", "exposure", source_domain="anime", source_id=1, rec_ids=[2, 3])
    assert "person@example.com" not in str(event)
    assert event["variant"] in AB_VARIANTS and event["rec_ids"] == [2, 3]


def test_log_event_never_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(event: dict[str, Any]) -> None:
        raise pool.DatabaseUnavailable("down")

    monkeypatch.setattr(events.queries, "insert_ab_event", fail)
    assert events.log_event("a@b.co", "exposure") is False


def test_search_titles_uses_parameters_and_escapes_wildcards(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def fake_fetch_all(sql: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        captured.update(sql=sql, params=params)
        return [{"id": 1, "title": "Cowboy Bebop"}]

    monkeypatch.setattr(queries, "fetch_all", fake_fetch_all)
    assert queries.search_titles("anime", "100%_Bebop'; drop table users;--")[0]["id"] == 1
    assert "drop table" not in captured["sql"]
    assert captured["params"]["pattern"] == "%100\\%\\_bebop'; drop table users;--%"


def test_queries_reject_unknown_domain() -> None:
    with pytest.raises(ValueError):
        queries.search_titles("films", "x")


def test_get_recommendations_selects_columns_by_name(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(queries, "fetch_all", lambda sql, params: [{"rank": 1, "id": 7, "title": "T"}])
    rows = queries.get_recommendations("anime", 1, "control")
    assert rows[0]["id"] == 7


def test_db_settings_prefers_prefixed_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pool, "_dotenv", lambda: {"user": "legacy", "password": "p", "host": "h", "port": "1",
                                                  "dbname": "d"})  # fmt: skip
    monkeypatch.setenv("DB_USER", "modern")
    settings = pool.db_settings()
    assert settings["user"] == "modern" and settings["host"] == "h"


def test_db_settings_reports_missing_values(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pool, "_dotenv", lambda: {})
    for key in ("DB_USER", "DB_PASSWORD", "DB_HOST", "DB_PORT", "DB_NAME"):
        monkeypatch.delenv(key, raising=False)
    with pytest.raises(pool.DatabaseUnavailable):
        pool.db_settings()


def test_decode_copy_field() -> None:
    assert decode_field("\\N") is None
    assert decode_field("a\\tb\\nc\\\\d") == "a\tb\nc\\d"


def test_theme_mapping() -> None:
    assert anime_themes(["Mecha", "Action", "Award Winning"]) == ["action", "mecha", "sci_fi"]
    assert "sci_fi" in game_themes(["Action"], "Pilot a spaceship across the galaxy to fight aliens.")
    assert "fantasy" not in game_themes([], "A single dragon appears.")  # One keyword is not enough.
    assert jaccard(["a", "b"], ["b", "c"]) == pytest.approx(1 / 3)


def test_pg_array_quotes_elements() -> None:
    assert pg_array(["Idols (Female)", 'a"b']) == '{"Idols (Female)","a\\"b"}'


def test_fixtures_are_deterministic() -> None:
    items_a, recs_a = fixtures()
    items_b, recs_b = fixtures()
    assert items_a.equals(items_b) and recs_a.equals(recs_b)
    assert set(recs_a["variant"]) == set(AB_VARIANTS)


def test_db_settings_accepts_db_name(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pool, "_dotenv", lambda: {"DB_USER": "u", "DB_PASSWORD": "p", "DB_HOST": "h",
                                                  "DB_PORT": "5432", "DB_NAME": "postgres"})  # fmt: skip
    for key in ("DB_USER", "DB_PASSWORD", "DB_HOST", "DB_PORT", "DB_NAME", "DB_DBNAME"):
        monkeypatch.delenv(key, raising=False)
    assert pool.db_settings()["dbname"] == "postgres"


def test_item_rows_strip_broken_characters() -> None:
    items, _ = fixtures(n_per_domain=5)
    items.loc[0, ["title", "alt_title", "synopsis"]] = ["Sekiro�", "Alt\x00", "Story�."]
    row = next(iter(_item_rows(items, "anime")))
    assert row[1:4] == ("Sekiro", "Alt", "Story.")
