"""Text cleaning for MyAnimeList synopses and Steam descriptions."""

from __future__ import annotations

import html
import re
import unicodedata
import warnings

from bs4 import BeautifulSoup, MarkupResemblesLocatorWarning

warnings.filterwarnings("ignore", category=MarkupResemblesLocatorWarning)

NO_SYNOPSIS = "No synopsis available."

_DROP_TAGS = ("img", "script", "style", "video", "iframe", "source")
_BOILERPLATE = re.compile(
    r"\[\s*written by mal rewrite\s*\]|\(\s*source:[^)]*\)|\bmal rewrite\b",
    flags=re.IGNORECASE,
)
_WHITESPACE = re.compile(r"[ \t ]+")  # noqa: RUF001
_BLANK_LINES = re.compile(r"\n{2,}")


def clean_synopsis(html_text: str | None) -> str:
    """Remove markup and boilerplate. Return readable plain text with one paragraph per line."""
    if not html_text or not html_text.strip():
        return NO_SYNOPSIS
    if "<" in html_text and ">" in html_text:
        soup = BeautifulSoup(html_text, "html.parser")
        for tag in soup(list(_DROP_TAGS)):
            tag.decompose()
        for br in soup.find_all("br"):
            br.replace_with("\n")
        text = soup.get_text(separator="\n")
    else:
        text = html_text
    text = html.unescape(text)
    text = unicodedata.normalize("NFKC", text)
    text = _BOILERPLATE.sub(" ", text)
    lines = [_WHITESPACE.sub(" ", line).strip() for line in text.splitlines()]
    text = "\n".join(line for line in lines if line)
    text = _BLANK_LINES.sub("\n", text)
    return text or NO_SYNOPSIS


def merge_descriptions(*parts: str | None) -> str:
    """Join cleaned description fields. Drop a field when a longer field already contains it."""
    cleaned = [c for c in (clean_synopsis(p) for p in parts) if c != NO_SYNOPSIS]
    kept: list[str] = []
    for text in sorted(cleaned, key=len, reverse=True):
        if not any(text.casefold() in other.casefold() for other in kept):
            kept.append(text)
    ordered = [text for text in cleaned if text in kept]
    return "\n".join(dict.fromkeys(ordered)) if ordered else NO_SYNOPSIS


def truncate(text: str, max_chars: int) -> str:
    """Cut text at the last word boundary before `max_chars` and add an ellipsis."""
    if len(text) <= max_chars:
        return text
    cut = text[:max_chars].rsplit(" ", 1)[0].rstrip(" ,.;:")
    return f"{cut}..."


# C0 and C1 control characters except tab, line feed and carriage return, plus U+FFFD from bad decoding.
_BROKEN_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f\ufffd]")
_ANY_SPACE = re.compile(r"\s+")


# A changelog header: a version number, or Patch/Update/Hotfix/Changelog followed by notes, a number or a colon.
_PATCH_HEADER = re.compile(
    r"^\s*(?:[-*•·]\s*)?(?:"
    r"v(?:er(?:sion)?)?\.?\s?\d+(?:\.\d+)+\b"
    r"|(?:patch|update|hotfix|changelog|change log|release notes)"
    r"(?:\s*(?:notes?|log)\b|\s*#?\s*v?\d|\s*[:!(\[-]|\s*$)"
    r")",
    flags=re.IGNORECASE,
)
# A changelog item: an optional bullet or [tag], then a past-tense change verb.
_PATCH_ITEM = re.compile(
    r"^\s*(?:[-*•·]\s*)?(?:\[[^\]]{0,40}\]\s*)?"
    r"(?:fixed|added|removed|changed|improved|updated|tweaked|adjusted|reduced|increased|optimi[sz]ed)\b",
    flags=re.IGNORECASE,
)


def drop_patch_notes(text: str) -> str:
    """Drop changelog lines from a plain-text description. Always keep the first line.

    Drop a header line (version number, Patch, Update, Hotfix, Changelog) and the item lines after it.
    Drop an item line ("Fixed ...", "- Added ...") only inside a header block or a run of two or more items.
    Keep every other line, so ordinary feature text survives.
    """
    lines = text.split("\n")
    if len(lines) < 2:
        return text
    is_item = [bool(_PATCH_ITEM.match(line)) for line in lines]
    kept, in_block = [lines[0]], False
    for i in range(1, len(lines)):
        line = lines[i]
        if _PATCH_HEADER.match(line):
            in_block = True
            continue
        if is_item[i]:
            in_run = is_item[i - 1] or (i + 1 < len(lines) and is_item[i + 1])
            if in_block or in_run:
                continue
        in_block = False
        kept.append(line)
    return "\n".join(kept)


def strip_broken_chars(text: str | None) -> str | None:
    """Remove U+FFFD and control characters. Keep line breaks. Return None for missing input."""
    if not isinstance(text, str):
        return None
    return _BROKEN_CHARS.sub("", text.replace("\r\n", "\n").replace("\r", "\n"))


def clean_title(title: str | None) -> str | None:
    """Remove broken characters, put each whitespace run on one line as one space. Return None when empty."""
    stripped = strip_broken_chars(title)
    if stripped is None:
        return None
    return _ANY_SPACE.sub(" ", stripped).strip() or None


def normalise_title(title: str) -> str:
    """Return a case-folded, accent-free title key for deduplication."""
    decomposed = unicodedata.normalize("NFKD", title)
    ascii_only = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return re.sub(r"[^0-9a-z]+", " ", ascii_only.casefold()).strip()


def https_image_url(url: str | None) -> str | None:
    """Return the URL over HTTPS, or None. Migration 002 rejects any other scheme in image_url."""
    if not url or not isinstance(url, str):
        return None
    url = url.strip()
    scheme, sep, rest = url.partition("://")
    if not sep or scheme.lower() not in ("http", "https") or not rest:
        return None
    return "https://" + rest  # The database check is case-sensitive, so write the scheme in lower case.
