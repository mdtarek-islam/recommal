"""AppTest fixtures. Every database call goes to an in-memory fake, so no test needs credentials."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

import auth_utils
from src.ab_testing.cohort import assign_variant
from src.db import queries
from src.ui import data

APP = str(Path(__file__).resolve().parents[2] / "app.py")
PASSWORD = "correct-horse-battery"
EMAIL = "reader@example.com"

ITEMS: dict[tuple[str, int], dict[str, Any]] = {
    ("anime", 1): {
        "id": 1,
        "title": "Cowboy Bebop",
        "synopsis": "Bounty hunters travel through space. " * 20,
        "image_url": "https://cdn.myanimelist.net/images/anime/4/19644.jpg",
        "year": 1998,
        "popularity": 10,
        "genres": [],
        "themes": ["sci_fi", "action", "crime"],
    },
    ("game", 7): {
        "id": 7,
        "title": "Outer Wilds",
        "synopsis": "Explore a solar system caught in a time loop.",
        "image_url": "https://evil.example.com/x.jpg",
        "year": 2019,
        "popularity": 5,
        "genres": [],
        "themes": ["sci_fi", "mystery"],
    },
}


def recs_for(domain: str) -> list[dict[str, Any]]:
    target = "game" if domain == "anime" else "anime"
    return [
        {"rank": i, "score": 0.9 - i / 10, "id": 100 + i, "title": f"{target.title()} pick {i}",
         "synopsis": "A [link](https://evil.example.com) and ![img](https://evil.example.com/i.png) in text.",
         "image_url": None, "year": 2000 + i, "genres": [], "themes": ["sci_fi", "drama", "mystery", "horror"]}
        for i in range(1, 6)
    ]  # fmt: skip


@dataclass
class FakeDb:
    """Records calls and returns fixture rows. Set `fail` to make every read raise."""

    events: list[dict[str, Any]] = field(default_factory=list)
    login_calls: int = 0
    matches: list[dict[str, Any]] = field(default_factory=lambda: [
        {"id": 1, "title": "Cowboy Bebop", "alt_title": "Kaubôi Bibappu", "year": 1998, "popularity": 10},
    ])  # fmt: skip
    fail: BaseException | None = None
    rec_count: int = 5  # Query-level filters can return fewer than 5 recommendations.

    def _check(self) -> None:
        if self.fail is not None:
            raise self.fail

    def search_titles(self, domain: str, query: str, **_: Any) -> list[dict[str, Any]]:
        self._check()
        return list(self.matches)

    def get_item(self, domain: str, item_id: int) -> dict[str, Any] | None:
        self._check()
        return ITEMS.get((domain, item_id)) or (
            {
                "id": item_id,
                "title": f"Title {item_id}",
                "synopsis": "",
                "image_url": None,
                "year": None,
                "popularity": 0,
                "genres": [],
                "themes": [],
            }
            if item_id >= 100
            else None
        )

    def get_recommendations(self, domain: str, item_id: int, variant: str) -> list[dict[str, Any]]:
        self._check()
        return recs_for(domain)[: self.rec_count] if item_id != 2 else []

    def get_user_hash(self, email: str) -> dict[str, Any] | None:
        self.login_calls += 1
        return {"email": EMAIL, "password_hash": HASH} if email.lower() == EMAIL else None

    def insert_ab_event(self, event: dict[str, Any]) -> None:
        self.events.append(event)

    def count_recent_login_failures(self, email_hash: str, window_minutes: int) -> int:
        return 0  # The server-side throttle belongs to auth_utils tests. Keep it open here.

    def record_login_attempt(self, email_hash: str, succeeded: bool, retention_hours: int) -> None:
        return None


HASH = auth_utils.hash_password(PASSWORD)


@pytest.fixture
def fake_db(monkeypatch: pytest.MonkeyPatch) -> Iterator[FakeDb]:
    db = FakeDb()
    for name in (
        "search_titles",
        "get_item",
        "get_recommendations",
        "get_user_hash",
        "insert_ab_event",
        "count_recent_login_failures",
        "record_login_attempt",
    ):
        monkeypatch.setattr(queries, name, getattr(db, name))
    monkeypatch.setattr(data.pool, "get_pool", lambda: object())
    st.cache_data.clear()
    st.cache_resource.clear()
    yield db
    st.cache_data.clear()
    st.cache_resource.clear()


def email_for(variant: str) -> str:
    """Return a test email that the experiment assigns to `variant`."""
    return next(e for i in range(1000) if assign_variant(e := f"user{i}@example.com") == variant)


@pytest.fixture
def make_app(fake_db: FakeDb) -> Callable[..., AppTest]:
    def build(logged_in: bool = False, email: str = EMAIL, **params: str) -> AppTest:
        at = AppTest.from_file(APP, default_timeout=30)
        if logged_in:
            at.session_state["logged_in"] = True
            at.session_state["user_email"] = email
        for key, value in params.items():
            at.query_params[key] = value
        return at

    return build
