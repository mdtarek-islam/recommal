"""Reusable Streamlit view components and the app style sheet."""

from __future__ import annotations

import html
import re
from collections.abc import Callable, Sequence
from typing import Any
from urllib.parse import urlsplit

import streamlit as st

from src.config import IMAGE_HOST_ALLOWLIST
from src.ingest.clean import truncate

DOMAIN_LABEL = {"anime": "Anime", "game": "Game"}
DOMAIN_PLURAL = {"anime": "Anime", "game": "Games"}
SEARCH_EXAMPLE = {"anime": "For example: Cowboy Bebop", "game": "For example: Stardew Valley"}
CARD_SYNOPSIS_CHARS = 160
# The card clamps its synopsis to 4 lines. At the narrowest card width 4 lines hold about
# 60 characters, so longer text also gets the "Full synopsis" expander.
CARD_EXPAND_CHARS = 60
INPUT_SYNOPSIS_CHARS = 400
CARD_THEMES = 3
CARD_FALLBACK_WIDTH_PX = 220

# One visual system. Spacing scale: 0.25, 0.5, 0.75, 1 and 1.5 rem.
# Type sizes: 1rem body and 0.875rem secondary text, plus the theme heading sizes.
# The accent comes from .streamlit/config.toml. light-dark() follows the theme that Streamlit
# applies to the app container through the CSS color-scheme property.
CSS = """
<style>
:root {
  --rc-accent: light-dark(#1F5FBF, #7EA6F2);
  --rc-muted: light-dark(#4A5160, #A9B0BC);
  --rc-border: light-dark(#C9CED6, #3A404B);
  --rc-surface: light-dark(#F3F4F6, #1A1D24);
}
.block-container {max-width: 1200px; padding: 1.5rem 1.5rem 3rem;}
@media (max-width: 640px) {
  .block-container {padding: 1rem 1rem 2rem;}
  h1 {font-size: 2rem !important;}
  h2 {font-size: 1.5rem !important;}
}

/* Primary buttons: white text on the light accent, dark text on the dark accent. */
[data-testid^="stBaseButton-primary"], [data-testid^="stBaseButton-primary"] p {
  color: light-dark(#FFFFFF, #0E1117) !important;
}
/* Text inputs show focus on their wrapper border, so they need no second outline. */
:where(button, a, summary, [role="tab"]):focus-visible {
  outline: 2px solid var(--rc-accent) !important;
  outline-offset: 2px;
}

.rc-muted {color: var(--rc-muted); font-size: 0.875rem; margin: 0;}
.rc-crumb {color: var(--rc-muted); font-size: 0.875rem; margin: 0; overflow-wrap: anywhere;}
.rc-crumb ol {
  list-style: none; display: flex; flex-wrap: wrap; gap: 0.25rem; padding: 0 !important; margin: 0 !important;
}
.rc-crumb li {margin: 0 !important; padding: 0 !important;}
.rc-crumb li + li::before {content: "/"; padding-right: 0.25rem;}
.rc-title {font-weight: 600; font-size: 1rem; line-height: 1.35; margin: 0; overflow-wrap: anywhere;}
.rc-themes {
  list-style: none; display: flex; flex-wrap: wrap; gap: 0.25rem; padding: 0 !important; margin: 0 !important;
}
.rc-themes li {
  margin: 0 !important; padding: 0 0.5rem !important; font-size: 0.875rem; line-height: 1.6;
  border: 1px solid var(--rc-border); border-radius: 4px;
}

/* Covers: one fixed aspect ratio for each domain. */
.rc-cover-missing {
  display: flex; align-items: center; justify-content: center; width: 100%;
  background: var(--rc-surface); border: 1px solid var(--rc-border); border-radius: 6px;
  color: var(--rc-muted); font-size: 0.875rem;
}
[data-testid="stImage"] img {border-radius: 6px; object-fit: cover; width: 100%; height: auto;}
.rc-cover-game, [class*="st-key-rec-card-game"] [data-testid="stImage"] img {aspect-ratio: 460 / 215;}
.rc-cover-anime, [class*="st-key-rec-card-anime"] [data-testid="stImage"] img {aspect-ratio: 2 / 3;}
.st-key-input-cover {max-width: 220px;}

/* Recommendation grid: 5 columns on desktop, 3 on tablet, 1 on phones. */
.st-key-rec-grid {
  display: grid !important; grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: 1rem; align-items: stretch;
}
.st-key-rec-grid > * {width: auto !important; min-width: 0; max-width: none !important; flex: none !important;}
[class*="st-key-rec-card-"] {height: 100%;}
[class*="st-key-rec-card-"] [data-testid="stText"] {font-size: 0.875rem;}
/* Card body: the synopsis shows at most 4 lines; the actions sit at the bottom of the card,
   so the buttons and thumbs line up across a row. */
[class*="st-key-rec-synopsis-"] [data-testid="stText"] {
  display: -webkit-box !important; -webkit-box-orient: vertical; -webkit-line-clamp: 4; line-clamp: 4;
  overflow: hidden; line-height: 1.5;
}
/* st.text wraps its text in an inline-block span, which blocks the clamp ellipsis. */
[class*="st-key-rec-synopsis-"] [data-testid="stText"] > span {
  display: inline; font-size: inherit; line-height: inherit; vertical-align: baseline;
}
/* Streamlit wraps a keyed container in a layout div; that wrapper is the flex item. */
[class*="st-key-rec-card-"] > :has(> [class*="st-key-rec-actions-"]) {margin-top: auto;}
@media (min-width: 560px) {
  [class*="st-key-rec-synopsis-"] [data-testid="stText"] {height: 6em;}
}
@media (max-width: 1023px) {.st-key-rec-grid {grid-template-columns: repeat(3, minmax(0, 1fr));}}
@media (max-width: 559px) {
  .st-key-rec-grid {grid-template-columns: minmax(0, 1fr);}
  .rc-cover-anime, [class*="st-key-rec-card-anime"] [data-testid="stImage"] img {
    aspect-ratio: 16 / 10; object-position: center 20%;
  }
}

.st-key-login-card {max-width: 28rem; margin-inline: auto;}

/* Search hint: the browser shows the field state at once; the server sees text only after Enter. */
.stApp:has(.st-key-query_input input:not(:placeholder-shown)) .st-key-hint-empty,
.stApp:not(:has(.st-key-query_input input:not(:placeholder-shown))) .st-key-hint-typed {display: none !important;}

/* Covers need no fullscreen control. The app shows no charts or tables. */
[data-testid="stElementToolbar"] {display: none !important;}

/* Touch targets: at least 44px on phones and touch screens. Streamlit selectors are more specific. */
@media (max-width: 640px), (pointer: coarse) {
  button, [role="tab"], summary, .stTextInput input {min-height: 44px !important;}
  button, [role="tab"] {min-width: 44px !important;}
}

@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after {
    animation-duration: 0.01ms !important; animation-iteration-count: 1 !important;
    transition-duration: 0.01ms !important; scroll-behavior: auto !important;
  }
}
</style>
"""

ABOUT_TEXT = """
Recommal places anime and video games in one shared space.
A sentence-BERT model turns each synopsis into a vector.
A Siamese network maps both domains into the same latent space.
Titles with a similar story, mood or theme sit close together in that space.
The app shows the nearest titles from the other domain.
The app ranks the matches by closeness. It does not score them as a percentage.
The results are suggestions based on synopsis and themes. They are not a quality rating.
Your thumbs-up and thumbs-down votes help us measure the results.
"""

# Characters that start Markdown links, images, emphasis, code, HTML, LaTeX or colour directives.
_MARKDOWN_SPECIAL = re.compile(r"([\\`*_\[\]<>$~|!#])")


def apply_styles() -> None:
    """Inject the style sheet. A style-only st.html block takes no layout space."""
    st.html(CSS)


def md_escape(text: Any) -> str:
    """Escape Markdown so catalogue or user text renders as plain text in Markdown elements."""
    return _MARKDOWN_SPECIAL.sub(r"\\\1", str(text))


def domain_label(domain: Any) -> str:
    """Return the display label for a domain key."""
    return DOMAIN_LABEL.get(str(domain), str(domain))


_THEME_LABELS = {"sci_fi": "Sci-fi"}


def theme_label(theme: str) -> str:
    """Return a sentence-case label for a theme key, for example "Slice of life"."""
    key = str(theme).strip().lower()
    return _THEME_LABELS.get(key, key.replace("_", " ").capitalize())


def match_label(match: dict[str, Any]) -> str:
    """Return the button label for one search match: title, year and alternative title."""
    label = str(match["title"]) + (f" ({match['year']})" if match.get("year") else "")
    if match.get("alt_title") and match["alt_title"] != match["title"]:
        label += f" - {match['alt_title']}"
    return md_escape(label)


def safe_image_url(url: Any) -> str | None:
    """Return the URL when it uses https and an allow-listed host. Return None otherwise."""
    if not isinstance(url, str) or not url.strip():
        return None
    try:
        parts = urlsplit(url.strip())
        port = parts.port
    except ValueError:
        return None
    host = (parts.hostname or "").lower()
    if parts.scheme != "https" or not host or parts.username or parts.password or port not in (None, 443):
        return None
    for pattern in IMAGE_HOST_ALLOWLIST:
        if host == pattern or (pattern.startswith("*.") and host.endswith(pattern[1:])):
            return url.strip()
    return None


def show_cover(item: dict[str, Any], domain: str) -> None:
    """Show the cover image, or a labelled placeholder when the URL is missing or not allowed."""
    title = str(item.get("title") or "this title")
    url = safe_image_url(item.get("image_url"))
    if url:
        st.image(url, width="stretch", alt=f"Cover image for {title}")
        return
    st.html(
        f"<div class='rc-cover-missing rc-cover-{html.escape(domain)}' role='img' "
        f"aria-label='No cover image for {html.escape(title, quote=True)}'>No cover image</div>"
    )


def show_themes(themes: Sequence[str], limit: int = CARD_THEMES) -> None:
    labels = [theme_label(t) for t in themes[:limit]]
    if labels:
        items = "".join(f"<li>{html.escape(label)}</li>" for label in labels)
        st.html(f"<ul class='rc-themes' aria-label='Themes'>{items}</ul>")


def show_breadcrumb(domain: str, title: str) -> None:
    st.html(
        "<nav class='rc-crumb' aria-label='Breadcrumb'><ol>"
        f"<li>Search</li><li>{html.escape(domain_label(domain))}</li>"
        f"<li aria-current='page'>{html.escape(title)}</li></ol></nav>"
    )


def show_synopsis(synopsis: str | None, limit: int, expander_label: str, expand_over: int | None = None) -> None:
    """Show plain synopsis text. st.text does not render Markdown or HTML from the catalogue.

    Show the full text in an expander when it is longer than `expand_over` (default: `limit`).
    """
    text = (synopsis or "").strip()
    if not text:
        st.html("<p class='rc-muted'>No synopsis is available.</p>")
        return
    st.text(truncate(text, limit), width="stretch")
    if len(text) > (limit if expand_over is None else expand_over):
        with st.expander(expander_label):
            st.text(text, width="stretch")


def show_input_item(item: dict[str, Any], domain: str) -> None:
    st.subheader(md_escape(item["title"]))
    left, right = st.columns([1, 3], gap="medium")
    with left, st.container(key="input-cover"):
        show_cover(item, domain)
    with right:
        year = f" - {item['year']}" if item.get("year") else ""
        st.html(f"<p class='rc-muted'>{html.escape(domain_label(domain) + year)}</p>")
        show_themes(item.get("themes") or [], limit=5)
        show_synopsis(item.get("synopsis"), INPUT_SYNOPSIS_CHARS, "Full synopsis")


NO_SHARED_THEMES = "No shared themes found; matched on synopsis wording."
_ORDINAL_SUFFIX = {1: "st", 2: "nd", 3: "rd"}


def similarity_label(position: int) -> str:
    """Return a rank label for a 1-based list position.

    Cosine scores of the top results sit close together, so a percentage misleads.
    The label states the rank within the list only.
    """
    if position <= 1:
        return "Closest match"
    suffix = "th" if 10 <= position % 100 <= 20 else _ORDINAL_SUFFIX.get(position % 10, "th")
    return f"{position}{suffix} closest"


def show_recommendation_card(
    rec: dict[str, Any],
    rec_domain: str,
    source_themes: list[str],
    explained: bool,
    feedback_key: str,
    on_feedback: Callable[[int, str], None],
    on_open: Callable[[str, int], None],
    position: int = 1,
) -> None:
    """Render one card. Only the `explained` variant shows the rank and shared themes."""
    rec_id = int(rec["id"])
    # The fixed width wraps cards into rows before the style sheet loads; the CSS grid then takes over.
    with st.container(border=True, key=f"rec-card-{rec_domain}-{rec_id}", width=CARD_FALLBACK_WIDTH_PX):
        show_cover(rec, rec_domain)
        st.html(f"<p class='rc-title' role='heading' aria-level='3'>{html.escape(str(rec['title']))}</p>")
        if rec.get("year"):
            st.html(f"<p class='rc-muted'>{html.escape(str(rec['year']))}</p>")
        show_themes(rec.get("themes") or [])
        if explained:
            st.badge(similarity_label(position), color="primary")
            shared = sorted(set(source_themes) & set(rec.get("themes") or []))
            themes_text = ", ".join(theme_label(t) for t in shared)
            explanation = f"Shared themes: {themes_text}" if shared else NO_SHARED_THEMES
            st.html(f"<p class='rc-muted'>{html.escape(explanation)}</p>")
        with st.container(key=f"rec-synopsis-{rec_domain}-{rec_id}"):
            show_synopsis(rec.get("synopsis"), CARD_SYNOPSIS_CHARS, "Full synopsis", expand_over=CARD_EXPAND_CHARS)
        with st.container(key=f"rec-actions-{rec_domain}-{rec_id}"):
            st.button(
                "Use this as my starting title", key=f"open-{rec_domain}-{rec_id}", on_click=on_open,
                args=(rec_domain, rec_id), width="stretch",
            )  # fmt: skip
            st.html("<p class='rc-muted'>Is this a good match?</p>")
            st.feedback("thumbs", key=feedback_key, on_change=on_feedback, args=(rec_id, feedback_key))


# Runs in the page through components v2. Streamlit keeps the scroll position across reruns,
# so a new results view would otherwise open at the old position.
_SCROLL_TOP_JS = """
export default function () {
  const target = document.querySelector(".st-key-top-bar");
  if (target) target.scrollIntoView({block: "start"});
}
"""


def scroll_to_top(key: str) -> None:
    """Scroll the page to the top bar once. Pass a new `key` for each request."""
    component = st.components.v2.component("rc_scroll_top", html="<span hidden></span>", js=_SCROLL_TOP_JS)
    component(key=key)


def show_about() -> None:
    with st.expander("How the recommendations work"):
        st.markdown(ABOUT_TEXT)
