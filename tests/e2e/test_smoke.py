"""Browser smoke test for the login page at desktop and mobile widths."""

from __future__ import annotations

import os
import socket
from pathlib import Path
from urllib.parse import urlparse

import pytest
from playwright.sync_api import Page, expect

BASE_URL = os.environ.get("RECOMMAL_BASE_URL", "http://localhost:8501")
QA_DIR = Path(__file__).resolve().parents[2] / ".claude" / "qa"
VIEWPORTS = {"desktop": (1440, 900), "mobile": (375, 812)}


def _server_reachable() -> bool:
    parsed = urlparse(BASE_URL)
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        with socket.create_connection((parsed.hostname or "localhost", port), timeout=2):
            return True
    except OSError:
        return False


pytestmark = pytest.mark.skipif(not _server_reachable(), reason="Streamlit server is unreachable")


@pytest.mark.parametrize("name", list(VIEWPORTS))
def test_login_page_renders(page: Page, name: str) -> None:
    width, height = VIEWPORTS[name]
    page.set_viewport_size({"width": width, "height": height})
    page.goto(BASE_URL)
    expect(page.get_by_role("heading", name="Recommal").first).to_be_visible(timeout=30_000)
    expect(page.get_by_role("tab", name="Log in")).to_be_visible(timeout=30_000)
    page.wait_for_timeout(1000)
    QA_DIR.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(QA_DIR / f"login-{name}-{width}.png"), full_page=True)
