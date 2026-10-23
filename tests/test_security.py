"""Regression tests for security controls in the SQL layer and CI workflow."""

from pathlib import Path

import pytest

from auth_utils import MAX_PASSWORD_BYTES, validate_credentials
from src.db import queries

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("domain", ["anime; drop table users", "ANIME", "", "animes"])
def test_unknown_domain_never_reaches_sql(domain: str) -> None:
    with pytest.raises(ValueError):
        queries.search_titles(domain, "x")


def test_search_pattern_escapes_like_wildcards(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, object] = {}
    monkeypatch.setattr(queries, "fetch_all", lambda sql, params=None: seen.update(params=params) or [])
    queries.search_titles("anime", "100%_\\")
    assert seen["params"]["pattern"] == r"%100\%\_\\%"  # type: ignore[index]


def test_password_over_bcrypt_limit_is_rejected() -> None:
    assert validate_credentials("a@b.co", "x" * (MAX_PASSWORD_BYTES + 1)) is not None
    assert validate_credentials("a@b.co", "é" * 37) is not None  # 74 bytes


def test_ci_verifies_gitleaks_checksum_and_pins_actions() -> None:
    ci = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert "sha256sum -c" in ci
    assert "pull_request_target" not in ci
    for line in ci.splitlines():
        if "uses:" in line:
            assert "@v" in line or ("@" in line and len(line.split("@")[1].strip()) == 40), line
