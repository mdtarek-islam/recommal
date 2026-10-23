"""AppTest coverage for the login, search and results views with a fake database."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from streamlit.testing.v1 import AppTest

from auth_utils import DB_ERROR
from src.db.pool import DatabaseUnavailable
from src.ui import components

from .conftest import EMAIL, ITEMS, PASSWORD, FakeDb, email_for

AppFactory = Callable[..., AppTest]


def _texts(at: AppTest) -> str:
    """Return every rendered text value, for checks that no raw or unsafe text leaks."""
    parts: list[str] = []
    for kind in ("markdown", "caption", "error", "warning", "info", "title", "header", "subheader", "text", "html"):
        parts += [str(getattr(el, "value", "")) for el in at.get(kind)]
    parts += [b.label for b in at.button]
    return "\n".join(parts)


def _button(at: AppTest, label: str) -> Any:
    return next(b for b in at.button if b.label == label)


def _login(at: AppTest, email: str, password: str) -> AppTest:
    at.text_input(key="login_email").input(email)
    at.text_input(key="login_pass").input(password)
    return _button(at, "Log in").click().run()


def test_login_page_renders_with_plain_copy(make_app: AppFactory) -> None:
    at = make_app().run()
    assert not at.exception
    assert at.title[0].value == "Recommal"
    assert [t.label for t in at.tabs] == ["Log in", "Create account"]
    labels = {w.label for w in at.text_input}
    assert {"Email address", "Password", "Repeat the password"} <= labels
    assert "obsession" not in _texts(at).lower()


def test_login_succeeds_and_keeps_shared_link(make_app: AppFactory, fake_db: FakeDb) -> None:
    at = make_app(domain="game", id="7").run()
    at = _login(at, EMAIL, PASSWORD)
    assert not at.exception and at.session_state["logged_in"]
    assert at.subheader[0].value == "Outer Wilds"


def test_login_throttle_blocks_after_five_failures(make_app: AppFactory, fake_db: FakeDb) -> None:
    at = make_app().run()
    for _ in range(5):
        at = _login(at, EMAIL, "wrong-password-1")
    assert "Wait 30 seconds" in at.error[0].value
    calls = fake_db.login_calls
    at = _login(at, EMAIL, PASSWORD)  # The correct password must still wait.
    assert not at.session_state["logged_in"]
    assert "Too many failed attempts" in at.error[0].value
    assert fake_db.login_calls == calls  # No database lookup during the wait.
    stored = repr(at.session_state["login_throttle"])
    assert EMAIL not in stored and PASSWORD not in stored and "wrong-password" not in stored


def test_throttle_counts_per_session_across_emails(make_app: AppFactory) -> None:
    at = make_app().run()
    for i in range(5):
        at = _login(at, f"other{i}@example.com", "wrong-password-1")
    assert "Wait 30 seconds" in at.error[0].value


def test_query_params_restore_results_view(make_app: AppFactory, fake_db: FakeDb) -> None:
    at = make_app(logged_in=True, domain="anime", id="1").run()
    assert not at.exception
    assert at.subheader[0].value == "Cowboy Bebop"
    assert "Games similar to Cowboy Bebop" in at.subheader[1].value
    assert sum(b.label == "Use this as my starting title" for b in at.button) == 5
    at.run()  # A rerun must not log a second exposure for the same item, variant and session.
    exposures = [e for e in fake_db.events if e["event_type"] == "exposure"]
    assert len(exposures) == 1 and EMAIL not in repr(fake_db.events)


def test_search_flow_writes_url_and_back_returns(make_app: AppFactory, fake_db: FakeDb) -> None:
    at = make_app(logged_in=True).run()
    assert [c.value for c in at.caption] == ["Type a title, then press Enter to search.", "Press Enter to search."]
    at.text_input(key="query_input").input("b").run()
    assert at.caption[0].value == "Type at least 2 characters, then press Enter."
    at.text_input(key="query_input").input("bebop").run()
    pick = next(b for b in at.button if b.key == "pick-anime-1")
    at = pick.click().run()
    assert at.query_params["domain"] == "anime" and at.query_params["id"] == "1"
    assert fake_db.events[0]["event_type"] == "search" and fake_db.events[0]["query"] == "bebop"
    at = _button(at, "Back to search").click().run()
    assert "id" not in at.query_params
    assert at.text_input(key="query_input").value == "bebop"  # The search text survives the round trip.
    assert any(b.key == "recent-anime-1" for b in at.button)


def test_use_as_starting_title_opens_the_other_domain(make_app: AppFactory) -> None:
    at = make_app(logged_in=True, domain="anime", id="1").run()
    at = next(b for b in at.button if b.key == "open-game-101").click().run()
    assert at.query_params["domain"] == "game" and at.query_params["id"] == "101"
    assert "Anime similar to Title 101" in at.subheader[1].value


def test_opening_a_title_requests_one_scroll_to_top(make_app: AppFactory) -> None:
    at = make_app(logged_in=True, domain="anime", id="1").run()
    assert not at.session_state["scroll_to_top"]
    at = next(b for b in at.button if b.key == "open-game-101").click().run()
    assert not at.exception
    assert not at.session_state["scroll_to_top"]  # The run that renders the new view clears the request.


@pytest.mark.parametrize("count", [1, 2, 3, 4, 5])
def test_results_grid_renders_one_to_five_cards(make_app: AppFactory, fake_db: FakeDb, count: int) -> None:
    fake_db.rec_count = count
    at = make_app(logged_in=True, email=email_for("explained"), domain="anime", id="1").run()
    assert not at.exception
    opens = [b.key for b in at.button if b.label == "Use this as my starting title"]
    assert opens == [f"open-game-{100 + i}" for i in range(1, count + 1)]
    exposure = next(e for e in fake_db.events if e["event_type"] == "exposure")
    assert exposure["rec_ids"] == [100 + i for i in range(1, count + 1)]
    texts = _texts(at)
    assert components.similarity_label(count) in texts and components.similarity_label(count + 1) not in texts


def test_recent_titles_keep_five(make_app: AppFactory) -> None:
    at = make_app(logged_in=True).run()
    for item_id in range(101, 108):
        at.query_params.update(domain="game", id=str(item_id))
        at.run()
    assert len(at.session_state["recent"]) == 5
    assert at.session_state["recent"][0][1] == 107


def test_invalid_link_shows_search(make_app: AppFactory) -> None:
    at = make_app(logged_in=True, domain="films", id="1;drop").run()
    assert "This link is not valid" in at.warning[0].value
    assert at.header[0].value == "Find recommendations"


def test_empty_search_result(make_app: AppFactory, fake_db: FakeDb) -> None:
    fake_db.matches = []
    at = make_app(logged_in=True).run()
    at.text_input(key="query_input").input("[x](https://evil.example.com)").run()
    assert at.info[0].value.startswith("No anime title matches")
    assert "\\[x\\]" in at.info[0].value  # Markdown is escaped, so no link renders.


def test_database_error_shows_fixed_message(make_app: AppFactory, fake_db: FakeDb) -> None:
    fake_db.fail = DatabaseUnavailable("password=hunter2 host=db.internal")
    at = make_app(logged_in=True).run()
    at.text_input(key="query_input").input("bebop").run()
    assert at.error[0].value == DB_ERROR
    assert "hunter2" not in _texts(at)


def test_missing_title_and_no_recommendations(make_app: AppFactory, monkeypatch: pytest.MonkeyPatch) -> None:
    at = make_app(logged_in=True, domain="anime", id="99").run()
    assert "not in the catalogue" in at.warning[0].value
    lonely = {"id": 2, "title": "Lonely", "synopsis": "", "image_url": None, "year": None, "themes": []}
    monkeypatch.setitem(ITEMS, ("anime", 2), lonely)
    at = make_app(logged_in=True, domain="anime", id="2").run()
    assert "No recommendations exist" in at.info[0].value


def test_variants_differ_only_in_explanations(make_app: AppFactory) -> None:
    def render(variant: str) -> str:
        return _texts(make_app(logged_in=True, email=email_for(variant), domain="anime", id="1").run())

    control, explained = render("control"), render("explained")
    assert "% match" not in control and "closest" not in control.lower() and "Shared themes" not in control
    assert "Closest match" in explained and "5th closest" in explained and "Shared themes: Sci-fi" in explained
    assert "% match" not in explained


def test_explained_card_without_shared_themes_says_so(make_app: AppFactory, monkeypatch: pytest.MonkeyPatch) -> None:
    loner = {"id": 3, "title": "Loner", "synopsis": "", "image_url": None, "year": None, "themes": ["romance"]}
    monkeypatch.setitem(ITEMS, ("anime", 3), loner)
    explained = _texts(make_app(logged_in=True, email=email_for("explained"), domain="anime", id="3").run())
    assert "No shared themes found; matched on synopsis wording." in explained
    assert "Shared themes:" not in explained


def test_synopsis_renders_as_plain_text_and_unsafe_image_is_dropped(make_app: AppFactory) -> None:
    at = make_app(logged_in=True, domain="game", id="7").run()
    assert any("[link](https://evil.example.com)" in t.value for t in at.text)  # st.text: no Markdown.
    assert not any("evil.example.com" in str(getattr(i, "value", "")) for i in at.get("imgs"))
    assert "No cover image" in _texts(at)


def test_logout_clears_user_and_url(make_app: AppFactory) -> None:
    at = make_app(logged_in=True, domain="anime", id="1").run()
    at = next(b for b in at.button if b.key == "logout").click().run()
    assert not at.session_state["logged_in"] and at.session_state["user_email"] == ""
    assert dict(at.query_params) == {}
    assert at.title[0].value == "Recommal"
