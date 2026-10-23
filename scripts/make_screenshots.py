"""Regenerate the README screenshots and demo GIF from the real Supabase catalogue.

Developer tool. Run from the project root:

    .venv/Scripts/python.exe scripts/make_screenshots.py

The script starts this file as a Streamlit page on port 8603 (harness mode), drives it with
Playwright, writes optimised images to docs/assets/ and stops only the server that it started.

Harness mode runs the real app.py with the real components and theme, with these changes:
- The session starts signed in as a fake demo user. `?view=login` shows the login page instead.
- `?as=control` or `?as=explained` forces the A/B variant for the session.
- Login accepts any input and touches no database. Registration is refused.
- A/B event logging is a no-op. Every query runs in a read-only transaction; writes raise.
"""

from __future__ import annotations

import io
import os
import runpy
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "docs" / "assets"
PORT = 8603
BASE = f"http://localhost:{PORT}/"
SERVE_FLAG = "--serve"
MAX_PNG_BYTES = 400_000
MAX_GIF_BYTES = 3_000_000
GIF_WIDTH = 1000
DEMO_USER = "demo-user"  # Fake identity. The UI never shows it.
DEMO_EMAIL = "demo.user@example.com"  # Typed into the login form for the GIF only.

IMAGES_DONE_JS = """
() => [...document.images].every(i => i.complete && i.naturalWidth > 0)
"""

# Titles chosen from the seeded catalogue (ids in public.animes and public.steam_games).
COWBOY_BEBOP = ("anime", 1)
HOLLOW_KNIGHT = ("game", 31132)
STARDEW_VALLEY = ("game", 31440)  # Honest failure case: the anime matches are poor.


# ---------------------------------------------------------------- harness mode (inside Streamlit)
def serve() -> None:
    """Patch the data and telemetry layers, fake the signed-in state, then run app.py."""
    sys.path.insert(0, str(ROOT))
    import streamlit as st

    import auth_utils
    from src.ab_testing import cohort, events
    from src.db import pool, queries

    def read_only(fetch: Any) -> Any:
        def run(sql: str, params: Any = None) -> Any:
            with pool.cursor() as cur:
                cur.execute("set transaction read only")
                cur.execute(sql, params)
                if fetch == "one":
                    row = cur.fetchone()
                    return dict(row) if row else None
                return [dict(row) for row in cur.fetchall()]

        return run

    def refuse(*_: Any, **__: Any) -> Any:
        raise PermissionError("The screenshot harness is read-only.")

    def forced_variant(user_id: str, *_: Any, **__: Any) -> str:
        return "control" if user_id.endswith("+control") else "explained"

    queries.fetch_one = read_only("one")
    queries.fetch_all = read_only("all")
    queries.execute = refuse
    events.log_event = lambda *_, **__: True
    cohort.assign_variant = forced_variant
    auth_utils.login_user = lambda *_: (True, "")
    auth_utils.register_user = lambda *_: (False, auth_utils.REGISTER_MESSAGE)

    if "logged_in" not in st.session_state and st.query_params.get("view") != "login":
        variant = st.query_params.get("as", "explained")
        st.session_state["logged_in"] = True
        st.session_state["user_email"] = f"{DEMO_USER}+{variant}"

    runpy.run_path(str(ROOT / "app.py"), run_name="__main__")


# ---------------------------------------------------------------- driver mode (outside Streamlit)
def start_server() -> subprocess.Popen[bytes]:
    cmd = [sys.executable, "-m", "streamlit", "run", str(Path(__file__).resolve()), "--server.headless", "true",
           "--server.port", str(PORT), "--server.runOnSave", "false", "--", SERVE_FLAG]  # fmt: skip
    proc = subprocess.Popen(cmd, cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)  # noqa: S603
    for _ in range(60):
        try:
            urllib.request.urlopen(f"{BASE}_stcore/health", timeout=1)  # noqa: S310 - fixed localhost URL.
            return proc
        except OSError:
            time.sleep(1)
    proc.terminate()
    raise RuntimeError("The screenshot harness did not start.")


def settle(page: Any) -> None:
    """Wait for the script run, the style sheet and the cover images."""
    page.wait_for_selector("[data-testid=stApp]", timeout=30_000)
    page.wait_for_function("() => !document.querySelector('[data-testid=stStatusWidget]')", timeout=60_000)
    page.wait_for_function(
        "() => [...document.querySelectorAll('style')].some(s => s.textContent.includes('rc-accent'))", timeout=30_000
    )
    page.wait_for_timeout(600)
    wait_for_images(page)


def wait_for_images(page: Any) -> None:
    """Load lazy images now, then wait until each one has decoded. Report images that fail."""
    page.evaluate("() => document.querySelectorAll('img[loading=lazy]').forEach(i => { i.loading = 'eager'; })")
    try:
        page.wait_for_function(IMAGES_DONE_JS, timeout=20_000)
    except Exception:  # noqa: BLE001 - a slow image CDN must not stop the run.
        broken = page.evaluate("() => [...document.images].filter(i => !i.naturalWidth).map(i => i.alt)")
        print(f"warning: images not loaded after 20 s: {broken}")
    page.wait_for_timeout(300)


def open_view(page: Any, query: str) -> None:
    page.goto(BASE + query)
    settle(page)


def content_height(page: Any) -> int:
    # Streamlit scrolls an inner container, so read the height of that container.
    return int(page.evaluate(
        "() => Math.max(...[...document.querySelectorAll('[data-testid=stMain], "
        "[data-testid=stAppScrollToBottomContainer]')].map(e => e.scrollHeight), "
        "document.documentElement.scrollHeight)"
    ))  # fmt: skip


def capture(page: Any, max_height: int | None = None) -> bytes:
    """Return a PNG of the whole page, or of its top `max_height` pixels."""
    size = page.viewport_size
    # Measure twice: covers that load after the first resize make the page taller.
    for _ in range(2):
        height = content_height(page) + 24
        if max_height:
            height = min(height, max_height)
        page.set_viewport_size({"width": size["width"], "height": max(height, size["height"])})
        wait_for_images(page)
    png: bytes = page.screenshot()
    page.set_viewport_size(size)
    return png


def save_png(png: bytes, name: str) -> None:
    """Write the PNG. Quantise to a palette, then downscale, until it is under the size cap."""
    from PIL import Image

    image = Image.open(io.BytesIO(png)).convert("RGB")
    out = io.BytesIO()
    image.save(out, "PNG", optimize=True)
    candidate = image
    while out.tell() > MAX_PNG_BYTES:
        out = io.BytesIO()
        quantised = candidate.quantize(colors=256, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)
        quantised.save(out, "PNG", optimize=True)
        if out.tell() > MAX_PNG_BYTES:
            smaller = (int(candidate.width * 0.85), int(candidate.height * 0.85))
            candidate = candidate.resize(smaller, Image.Resampling.LANCZOS)
    (ASSETS / name).write_bytes(out.getvalue())
    print(f"{name}: {out.tell() // 1024} KB")


def save_gif(frames: list[bytes], name: str, frame_ms: int = 1300, last_ms: int = 2500) -> None:
    from PIL import Image

    images = []
    for png in frames:
        image = Image.open(io.BytesIO(png)).convert("RGB")
        if image.width != GIF_WIDTH:
            image = image.resize((GIF_WIDTH, round(image.height * GIF_WIDTH / image.width)), Image.Resampling.LANCZOS)
        images.append(image.quantize(colors=128, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE))
    durations = [frame_ms] * (len(images) - 1) + [last_ms]
    out = io.BytesIO()
    images[0].save(out, "GIF", save_all=True, append_images=images[1:], duration=durations, loop=0, optimize=True)
    if out.tell() > MAX_GIF_BYTES:
        raise RuntimeError(f"{name} is {out.tell()} bytes, over the {MAX_GIF_BYTES} byte cap.")
    (ASSETS / name).write_bytes(out.getvalue())
    print(f"{name}: {out.tell() // 1024} KB, {len(images)} frames")


def results_query(item: tuple[str, int], variant: str) -> str:
    return f"?domain={item[0]}&id={item[1]}&as={variant}"


def scroll_to(page: Any, selector: str) -> None:
    page.locator(selector).first.evaluate("e => e.scrollIntoView({block: 'start'})")
    page.wait_for_timeout(500)


def make_stills(browser: Any) -> None:
    desktop = browser.new_context(viewport={"width": 1440, "height": 900}, reduced_motion="reduce")
    page = desktop.new_page()
    open_view(page, "?view=login")
    save_png(capture(page), "login-desktop.png")
    open_view(page, "?domain=anime")
    box = page.get_by_label("Anime title")
    box.fill("Cowboy Bebop")
    box.press("Enter")
    settle(page)
    save_png(capture(page), "search-desktop.png")
    for name, item, variant in [
        ("results-anime-control-desktop.png", COWBOY_BEBOP, "control"),
        ("results-anime-explained-desktop.png", COWBOY_BEBOP, "explained"),
        ("results-game-explained-desktop.png", HOLLOW_KNIGHT, "explained"),
        ("results-weak-example.png", STARDEW_VALLEY, "control"),
    ]:
        open_view(page, results_query(item, variant))
        save_png(capture(page), name)
    desktop.close()

    dark = browser.new_context(viewport={"width": 1440, "height": 900}, color_scheme="dark", reduced_motion="reduce")
    page = dark.new_page()
    open_view(page, results_query(COWBOY_BEBOP, "explained"))
    save_png(capture(page), "results-dark-desktop.png")
    dark.close()

    mobile = browser.new_context(viewport={"width": 375, "height": 812}, reduced_motion="reduce")
    page = mobile.new_page()
    open_view(page, "?view=login")
    save_png(capture(page), "login-mobile.png")
    open_view(page, results_query(COWBOY_BEBOP, "explained"))
    save_png(capture(page, max_height=2400), "results-explained-mobile.png")
    mobile.close()


def make_gif(browser: Any) -> None:
    ctx = browser.new_context(viewport={"width": GIF_WIDTH, "height": 700}, reduced_motion="reduce")
    page = ctx.new_page()
    frames: list[bytes] = []
    open_view(page, "?view=login")
    frames.append(page.screenshot())
    page.get_by_label("Email address").first.fill(DEMO_EMAIL)
    page.get_by_label("Password", exact=True).fill("demo-password")
    frames.append(page.screenshot())
    page.get_by_role("button", name="Log in", exact=True).click()
    settle(page)
    frames.append(page.screenshot())
    box = page.get_by_label("Anime title")
    box.fill("Cowboy Bebop")
    frames.append(page.screenshot())
    box.press("Enter")
    settle(page)
    frames.append(page.screenshot())
    page.locator(".st-key-pick-anime-1 button").first.click()
    settle(page)
    frames.append(page.screenshot())
    scroll_to(page, ".st-key-rec-grid")
    frames.append(page.screenshot())
    # Open the 4th card. The 1st card (Halo) leads to an anime list with fan-service covers.
    page.get_by_role("button", name="Use this as my starting title").nth(3).click()
    settle(page)  # The app scrolls the new results view to the top bar.
    frames.append(page.screenshot())
    scroll_to(page, ".st-key-rec-grid")
    frames.append(page.screenshot())
    ctx.close()
    save_gif(frames, "demo.gif")


def main() -> int:
    from playwright.sync_api import sync_playwright

    ASSETS.mkdir(parents=True, exist_ok=True)
    server = start_server()
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            try:
                make_stills(browser)
                make_gif(browser)
            finally:
                browser.close()
    finally:
        server.terminate()
        try:
            server.wait(timeout=15)
        except subprocess.TimeoutExpired:
            server.kill()
    return 0


if __name__ == "__main__":
    if SERVE_FLAG in sys.argv:
        serve()
    else:
        os.chdir(ROOT)
        sys.exit(main())
