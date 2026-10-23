"""Unit tests for routing, throttling, safe rendering helpers and the A/B pseudonym."""

from __future__ import annotations

import hashlib
import logging
from typing import Any

import pytest

from src.ab_testing import cohort, events
from src.config import AB_EXPERIMENT, AB_VARIANTS
from src.ui import components, routing, throttle


class Params(dict[str, Any]):
    def from_dict(self, params: dict[str, Any]) -> None:
        self.clear()
        self.update(params)


@pytest.mark.parametrize(
    ("params", "expected"),
    [
        ({}, routing.Route()),
        ({"domain": "game"}, routing.Route(domain="game")),
        ({"domain": "anime", "id": "12"}, routing.Route(domain="anime", item_id=12)),
        ({"domain": "anime", "id": "0"}, routing.Route(domain="anime", invalid=True)),
        ({"domain": "anime", "id": "-3"}, routing.Route(domain="anime", invalid=True)),
        ({"domain": "anime", "id": "1" * 11}, routing.Route(domain="anime", invalid=True)),
        ({"domain": "anime", "id": "١٢"}, routing.Route(domain="anime", invalid=True)),
        ({"id": "5"}, routing.Route(invalid=True)),
        ({"domain": "films"}, routing.Route(invalid=True)),
    ],
)
def test_route_parsing(params: dict[str, str], expected: routing.Route) -> None:
    assert routing.read(Params(params)) == expected


def test_route_writers_replace_all_params() -> None:
    params = Params({"domain": "anime", "id": "3", "other": "x"})
    routing.write_search(params, "game")
    assert params == {"domain": "game"}
    routing.write_results(params, "anime", 9)
    assert params == {"domain": "anime", "id": "9"}


def test_throttle_waits_double_and_cap() -> None:
    assert [throttle.wait_for(n) for n in (4, 5, 6, 7)] == [0, 30, 60, 120]
    assert throttle.wait_for(100) == throttle.MAX_WAIT_S


def test_throttle_per_email_survives_session_reset() -> None:
    state = throttle.new_state()
    for _ in range(5):
        throttle.record_failure(state, "victim-hash", now=1000.0)
    throttle.record_success(state, "attacker-hash")  # Logging in to another account clears the session only.
    assert throttle.seconds_left(state, "victim-hash", now=1000.0) == 30
    assert throttle.seconds_left(state, "victim-hash", now=1031.0) == 0


def test_throttle_bounds_tracked_emails() -> None:
    state = throttle.new_state()
    for i in range(200):
        throttle.record_failure(state, f"hash-{i}", now=0.0)
    assert len(state) <= throttle.MAX_TRACKED_EMAILS + 2


@pytest.mark.parametrize(
    ("url", "allowed"),
    [
        ("https://cdn.myanimelist.net/images/a.jpg", True),
        ("https://shared.akamai.steamstatic.com/store/apps/1/header.jpg", True),
        ("https://cdn.akamai.steamstatic.com/steam/apps/1/header.jpg", True),
        ("http://cdn.myanimelist.net/a.jpg", False),
        ("https://cdn.myanimelist.net.evil.com/a.jpg", False),
        ("https://evilsteamstatic.com/a.jpg", False),
        ("https://user:pw@cdn.myanimelist.net/a.jpg", False),
        ("https://cdn.myanimelist.net:8443/a.jpg", False),
        ("https://cdn.myanimelist.net:99999/a.jpg", False),
        ("javascript:alert(1)", False),
        ("", False),
        (None, False),
    ],
)
def test_safe_image_url(url: Any, allowed: bool) -> None:
    assert (components.safe_image_url(url) is not None) is allowed


def test_md_escape_blocks_links_images_and_html() -> None:
    escaped = components.md_escape("![x](u) [y](v) <b>*z*</b> $a$ :red[t]")
    for raw in ("![", "[y]", "<b>", "*z*", "$a$", "[t]"):
        assert raw not in escaped


def test_hash_user_is_keyed_hmac(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RECOMMAL_AB_SALT", "key-one")
    first = cohort.hash_user("Person@Example.com ")
    assert first == cohort.hash_user("person@example.com") and len(first) == 64
    assert first != hashlib.sha256(b"key-one:person@example.com").hexdigest()
    monkeypatch.setenv("RECOMMAL_AB_SALT", "key-two")
    assert cohort.hash_user("person@example.com") != first


def test_assignment_matches_the_historic_formula(monkeypatch: pytest.MonkeyPatch) -> None:
    """Switching the pseudonym to HMAC must not move any live user to another variant."""
    monkeypatch.delenv("RECOMMAL_AB_SALT", raising=False)
    for i in range(300):
        email = f"user{i}@example.com"
        legacy = hashlib.sha256(f"recommal-ab:{email}".encode()).hexdigest()
        digest = hashlib.sha256(f"{AB_EXPERIMENT}:{legacy}".encode()).digest()
        assert cohort.assign_variant(email) == AB_VARIANTS[int.from_bytes(digest[:8], "big") % len(AB_VARIANTS)]


def test_missing_salt_warns_once(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    monkeypatch.delenv("RECOMMAL_AB_SALT", raising=False)
    monkeypatch.setattr(cohort, "_warned", False)
    with caplog.at_level(logging.WARNING, logger=cohort.__name__):
        cohort.hash_user("a@b.co")
        cohort.hash_user("c@d.co")
    assert sum("RECOMMAL_AB_SALT" in r.message for r in caplog.records) == 1


def test_event_query_is_capped() -> None:
    event = events.build_event("a@b.co", "search", query="x" * 500)
    assert len(event["query"]) == events.MAX_QUERY_CHARS


def test_event_write_failure_logs_no_message(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    def fail(event: dict[str, Any]) -> None:
        raise RuntimeError("password=hunter2")

    monkeypatch.setattr(events.queries, "insert_ab_event", fail)
    with caplog.at_level(logging.WARNING):
        assert events.log_event("a@b.co", "exposure") is False
    assert "hunter2" not in caplog.text and "a@b.co" not in caplog.text


@pytest.mark.parametrize(
    ("position", "label"),
    [(1, "Closest match"), (2, "2nd closest"), (3, "3rd closest"), (4, "4th closest"), (5, "5th closest"),
     (11, "11th closest"), (21, "21st closest")],
)  # fmt: skip
def test_similarity_label_states_rank_not_percentage(position: int, label: str) -> None:
    assert components.similarity_label(position) == label
    assert "%" not in components.similarity_label(position)


def test_about_text_promises_no_percentage() -> None:
    assert "%" not in components.ABOUT_TEXT
    assert "not a quality rating" in components.ABOUT_TEXT


@pytest.mark.parametrize(
    ("theme", "label"),
    [("slice_of_life", "Slice of life"), ("sci_fi", "Sci-fi"), ("martial_arts", "Martial arts"),
     ("action", "Action"), ("Slice_Of_Life", "Slice of life")],
)  # fmt: skip
def test_theme_label_uses_sentence_case(theme: str, label: str) -> None:
    assert components.theme_label(theme) == label
