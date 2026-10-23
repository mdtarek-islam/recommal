from typing import Any

import pytest

import auth_utils
from src.ingest.clean import https_image_url

# Keep the real query functions; the autouse fixture below replaces them for every test.
_REAL_COUNT = auth_utils.queries.count_recent_login_failures
_REAL_RECORD = auth_utils.queries.record_login_attempt


class _UndefinedTable(auth_utils.pg_errors.UndefinedTable):
    """Constructible stand-in for the psycopg2 error raised when a table is missing."""


@pytest.fixture(autouse=True)
def throttle_store(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, bool]]:
    """Replace the login_attempts queries with an in-memory store. No test reaches a real database."""
    attempts: list[tuple[str, bool]] = []

    def count(email_hash: str, window_minutes: int) -> int:
        failures = 0
        for h, ok in attempts:
            if h == email_hash:
                failures = 0 if ok else failures + 1
        return failures

    def record(email_hash: str, succeeded: bool, retention_hours: int) -> None:
        attempts.append((email_hash, succeeded))

    monkeypatch.setattr(auth_utils.queries, "count_recent_login_failures", count)
    monkeypatch.setattr(auth_utils.queries, "record_login_attempt", record)
    monkeypatch.setattr(auth_utils, "_throttle_missing_since", None)
    monkeypatch.setattr(auth_utils, "_throttle_warned", False)
    return attempts


def test_hash_and_check_password_round_trip() -> None:
    hashed = auth_utils.hash_password("correct horse")
    assert hashed != "correct horse"
    assert auth_utils.check_password(hashed, "correct horse")
    assert not auth_utils.check_password(hashed, "wrong horse")


def test_hash_uses_a_random_salt() -> None:
    assert auth_utils.hash_password("same password") != auth_utils.hash_password("same password")


def test_check_password_rejects_malformed_hash() -> None:
    assert not auth_utils.check_password("not-a-bcrypt-hash", "anything")


@pytest.mark.parametrize(
    ("email", "password", "expected"),
    [
        ("", "longenough", "required"),
        ("not-an-email", "longenough", "valid email"),
        ("a@b.co", "short", "at least 8"),
        ("a@b.co", "x" * 73, "at most 72"),
        ("a@b.co", "longenough", None),
    ],
)
def test_validate_credentials(email: str, password: str, expected: str | None) -> None:
    message = auth_utils.validate_credentials(email, password)
    assert (message is None) if expected is None else (expected in (message or ""))


def test_login_user_with_mocked_database(monkeypatch: pytest.MonkeyPatch) -> None:
    stored = {"email": "a@b.co", "password_hash": auth_utils.hash_password("longenough")}
    monkeypatch.setattr(auth_utils.queries, "get_user_hash", lambda email: stored)
    assert auth_utils.login_user("a@b.co", "longenough") == (True, "Login successful.")
    assert auth_utils.login_user("a@b.co", "wrongpass") == (False, auth_utils.LOGIN_ERROR)


def test_login_user_unknown_email_still_runs_bcrypt(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, str]] = []
    real_check = auth_utils.check_password

    def spy(hashed_password: str, user_password: str) -> bool:
        calls.append((hashed_password, user_password))
        return real_check(hashed_password, user_password)

    monkeypatch.setattr(auth_utils.queries, "get_user_hash", lambda email: None)
    monkeypatch.setattr(auth_utils, "check_password", spy)
    assert auth_utils.login_user("nobody@b.co", "longenough") == (False, auth_utils.LOGIN_ERROR)
    assert calls == [(auth_utils._DUMMY_HASH, "longenough")]


def test_login_user_reports_database_outage(monkeypatch: pytest.MonkeyPatch) -> None:
    def unavailable(email: str) -> dict[str, Any]:
        raise auth_utils.DatabaseUnavailable("down")

    monkeypatch.setattr(auth_utils.queries, "get_user_hash", unavailable)
    assert auth_utils.login_user("a@b.co", "longenough") == (False, auth_utils.DB_ERROR)


def test_register_user_duplicate_email_matches_new_email(monkeypatch: pytest.MonkeyPatch) -> None:
    def duplicate(email: str, password_hash: str) -> None:
        raise auth_utils.psycopg2.IntegrityError("duplicate")

    monkeypatch.setattr(auth_utils.queries, "insert_user", lambda email, password_hash: None)
    new = auth_utils.register_user("new@b.co", "longenough")
    monkeypatch.setattr(auth_utils.queries, "insert_user", duplicate)
    existing = auth_utils.register_user("a@b.co", "longenough")
    assert new == existing == (True, auth_utils.REGISTER_MESSAGE)
    assert "exists" not in auth_utils.REGISTER_MESSAGE


def test_register_user_keeps_validation_errors_specific(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(auth_utils.queries, "insert_user", lambda email, password_hash: None)
    ok, message = auth_utils.register_user("a@b.co", "short")
    assert not ok and "at least 8" in message


def test_register_user_reports_database_outage(monkeypatch: pytest.MonkeyPatch) -> None:
    def unavailable(email: str, password_hash: str) -> None:
        raise auth_utils.DatabaseUnavailable("down")

    monkeypatch.setattr(auth_utils.queries, "insert_user", unavailable)
    assert auth_utils.register_user("a@b.co", "longenough") == (False, auth_utils.DB_ERROR)


def test_login_throttle_blocks_after_five_failures(
    monkeypatch: pytest.MonkeyPatch, throttle_store: list[tuple[str, bool]]
) -> None:
    stored = {"email": "a@b.co", "password_hash": auth_utils.hash_password("longenough")}
    monkeypatch.setattr(auth_utils.queries, "get_user_hash", lambda email: stored)
    for _ in range(auth_utils.MAX_FAILED_ATTEMPTS):
        assert auth_utils.login_user("a@b.co", "wrongpass") == (False, auth_utils.LOGIN_ERROR)
    checks: list[str] = []
    monkeypatch.setattr(auth_utils, "check_password", lambda h, p: checks.append(p) or True)
    assert auth_utils.login_user("A@b.co ", "longenough") == (False, auth_utils.THROTTLE_ERROR)
    assert checks == []  # The throttle runs before bcrypt.
    assert all(h == auth_utils.hash_user("a@b.co") and "@" not in h for h, _ in throttle_store)


def test_login_throttle_message_is_the_same_for_unknown_emails(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(auth_utils.queries, "get_user_hash", lambda email: None)
    for _ in range(auth_utils.MAX_FAILED_ATTEMPTS):
        assert auth_utils.login_user("nobody@b.co", "longenough") == (False, auth_utils.LOGIN_ERROR)
    assert auth_utils.login_user("nobody@b.co", "longenough") == (False, auth_utils.THROTTLE_ERROR)


def test_login_success_resets_the_failure_count(
    monkeypatch: pytest.MonkeyPatch, throttle_store: list[tuple[str, bool]]
) -> None:
    stored = {"email": "a@b.co", "password_hash": auth_utils.hash_password("longenough")}
    monkeypatch.setattr(auth_utils.queries, "get_user_hash", lambda email: stored)
    for _ in range(auth_utils.MAX_FAILED_ATTEMPTS - 1):
        auth_utils.login_user("a@b.co", "wrongpass")
    assert auth_utils.login_user("a@b.co", "longenough") == (True, "Login successful.")
    assert throttle_store[-1][1] is True
    assert auth_utils.login_user("a@b.co", "wrongpass") == (False, auth_utils.LOGIN_ERROR)


def test_login_without_attempts_table_skips_throttle_and_warns_once(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    def missing(*args: Any) -> Any:
        raise _UndefinedTable("relation does not exist")

    stored = {"email": "a@b.co", "password_hash": auth_utils.hash_password("longenough")}
    monkeypatch.setattr(auth_utils.queries, "get_user_hash", lambda email: stored)
    monkeypatch.setattr(auth_utils.queries, "count_recent_login_failures", missing)
    monkeypatch.setattr(auth_utils.queries, "record_login_attempt", missing)
    with caplog.at_level("WARNING", logger="auth_utils"):
        for _ in range(auth_utils.MAX_FAILED_ATTEMPTS + 2):
            assert auth_utils.login_user("a@b.co", "wrongpass") == (False, auth_utils.LOGIN_ERROR)
        assert auth_utils.login_user("a@b.co", "longenough") == (True, "Login successful.")
    warnings = [r for r in caplog.records if "login_attempts" in r.getMessage()]
    assert len(warnings) == 1


def test_login_fails_closed_when_throttle_query_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    def broken(*args: Any) -> Any:
        raise auth_utils.psycopg2.OperationalError("connection lost")

    monkeypatch.setattr(auth_utils.queries, "count_recent_login_failures", broken)
    monkeypatch.setattr(auth_utils.queries, "get_user_hash", lambda email: None)
    assert auth_utils.login_user("a@b.co", "longenough") == (False, auth_utils.DB_ERROR)


def test_login_succeeds_when_recording_the_attempt_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    def broken(*args: Any) -> Any:
        raise auth_utils.psycopg2.OperationalError("connection lost")

    stored = {"email": "a@b.co", "password_hash": auth_utils.hash_password("longenough")}
    monkeypatch.setattr(auth_utils.queries, "get_user_hash", lambda email: stored)
    monkeypatch.setattr(auth_utils.queries, "record_login_attempt", broken)
    assert auth_utils.login_user("a@b.co", "longenough") == (True, "Login successful.")


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://cdn.example/a.jpg", "https://cdn.example/a.jpg"),
        ("HTTP://cdn.example/a.jpg", "https://cdn.example/a.jpg"),
        ("javascript:alert(1)", None),
        ("data://x", None),
        ("", None),
        (None, None),
    ],
)
def test_https_image_url(url: str | None, expected: str | None) -> None:
    assert https_image_url(url) == expected


def test_throttle_queries_use_bound_parameters(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[tuple[str, Any]] = []

    def fake_fetch_one(sql: str, params: Any) -> dict[str, int]:
        seen.append((sql, params))
        return {"failures": 3}

    def fake_execute(sql: str, params: Any) -> int:
        seen.append((sql, params))
        return 1

    monkeypatch.setattr(auth_utils.queries, "fetch_one", fake_fetch_one)
    monkeypatch.setattr(auth_utils.queries, "execute", fake_execute)
    assert _REAL_COUNT("abc", 15) == 3
    _REAL_RECORD("abc", False, 24)
    assert [params for _, params in seen] == [{"h": "abc", "window": 15}, {"h": "abc", "ok": False, "keep": 24}]
    assert all("abc" not in sql for sql, _ in seen)
