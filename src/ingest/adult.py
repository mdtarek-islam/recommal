"""Refine the adult-content flag with text signals from the title and synopsis.

The source flag uses only Steam genres and MyAnimeList ratings, and it misses many adult games.
Under-flagging shows adult targets for non-adult sources, so the rules below prefer recall.
Each strong rule scores 2 and each weak rule scores 1. A game needs a score of 2.
An anime needs a score of 3, because MyAnimeList ratings already flag most adult anime
and plot synopses often mention words such as "erotic manga" in passing.
"""

from __future__ import annotations

import re

import pandas as pd

# Each rule is (anchors, pattern). The regex runs only when one anchor occurs in the lower-case text.
# The anchor check is a fast substring scan, so the full catalogue takes seconds, not minutes.
Rule = tuple[tuple[str, ...], str]

# One match of any strong rule flags the item.
STRONG_RULES: dict[str, Rule] = {
    "hentai": (("hentai",), r"\bhentai\b"),
    "eroge": (("eroge",), r"\beroge\b"),
    "erotic": (("erotic",), r"\berotic(?:a|ism|ally)?\b"),
    "nsfw": (("nsfw",), r"\bnsfw\b"),
    "porn": (("porn",), r"\bporn(?:o|ography|ographic)?\b"),
    "18+": (("18+", "18 +", "r18", "r-18"), r"(?<![\w.])(?:18 ?\+|r-?18)(?![\w.])"),
    "adults only": (("adult",), r"\badults?[\s-]only\b"),
    "sexual content": (("sexual",), r"\bsexual (?:content|scenes?|acts?|themes?|situations?|intercourse)\b"),
    "nudity": (("nudity",), r"\bnudity\b"),
    "uncensored": (("uncensored",), r"\buncensored\b"),
    "explicit sex": (("explicit",), r"\bexplicit (?:sex\w*|content|scenes?|adult|material|images?|h-scenes?)\b"),
    "sex scenes": (("scene",), r"\b(?:sex|h)[\s-]scenes?\b"),
    "milf": (("milf",), r"\bmilfs?\b"),
    "creampie": (("creampie",), r"\bcreampie"),
    "futanari": (("futanari",), r"\bfutanari\b"),
    "ejaculation": (("ejaculat",), r"\bejaculat"),
    "orgasm": (("orgasm",), r"\borgasm"),
}

# Weak rules score 1 each. One weak rule alone never flags an item.
WEAK_RULES: dict[str, Rule] = {
    "ecchi": (("ecchi",), r"\becchi\b"),
    "sex": (("sex",), r"\bsex\b"),
    "sexy": (("sex",), r"\bsex(?:y|ier|iest|ual|ually|uality)\b"),
    "explicit": (("explicit",), r"\bexplicit\b"),
    "mommy": (("momm",), r"\bmomm(?:y|ies)\b"),
    "waifu": (("waifu",), r"\bwaifus?\b"),
    "horny": (("horny",), r"\bhorny\b"),
    "lewd": (("lewd",), r"\blewd"),
    "naughty": (("naught",), r"\bnaught(?:y|ier|iest)\b"),
    "oppai": (("oppai",), r"\boppai\b"),
    "busty": (("bust",), r"\bbust(?:y|ier|iest)\b"),
    "breasts": (
        ("breast", "boob", "tits", "titties", "milkers"),
        r"\b(?:breasts?|boobs?|boobies|tits|titties|milkers)\b",
    ),
    "nude": (("nude", "naked", "undress", "strip"), r"\b(?:nude|naked|undress\w*|strip(?:ping|tease)?)\b"),
    "fetish": (("fetish", "kink", "bdsm", "bondage"), r"\b(?:fetish|kink|bdsm\b|bondage\b)"),
    "seduce": (("seduc", "arous"), r"\b(?:seduc|arous)"),
    "succubus": (("succub",), r"\bsuccub(?:us|i)\b"),
    "panties": (("panties", "lingerie", "underwear"), r"\b(?:panties|lingerie|underwear)\b"),
    "harem": (("harem",), r"\bharem\b"),
    "xxx": (("xxx",), r"\bxxx\b"),
    "18 years": (("over 18", "age 18", "aged 18", "18 years"), r"\b(?:over|aged?) 18\b|\b18 years\b"),
}
STRONG_WEIGHT = 2
MIN_SCORE = {"game": 2, "anime": 3}
DEFAULT_MIN_SCORE = 2

# Remove negated phrases such as "no nudity" or "does not contain any sexual content" before matching.
_NEGATABLE = ("nudity", "sex", "explicit", "porn", "erotic", "nsfw")
_NEGATION = re.compile(
    r"\b(?:no|without|zero|free of|not (?:contain|include|feature)\w*(?: any)?)\s+(?:\w+\s+){0,2}?"
    r"(?:nudity|sex\w*|explicit\w*|porn\w*|erotic\w*|nsfw)\b"
)


def _compile(rules: dict[str, Rule]) -> list[tuple[str, tuple[str, ...], re.Pattern[str]]]:
    return [(name, anchors, re.compile(pattern)) for name, (anchors, pattern) in rules.items()]


_STRONG = _compile(STRONG_RULES)
_WEAK = _compile(WEAK_RULES)


def adult_signals(text: str) -> tuple[list[str], list[str]]:
    """Return the names of the strong and weak rules that match `text`, after negation removal."""
    low = text.lower()
    if any(word in low for word in _NEGATABLE):
        low = _NEGATION.sub(" ", low)
    strong = [n for n, anchors, rx in _STRONG if any(a in low for a in anchors) and rx.search(low)]
    weak = [n for n, anchors, rx in _WEAK if any(a in low for a in anchors) and rx.search(low)]
    return strong, weak


def adult_score(text: str) -> int:
    """Return 2 for each matching strong rule plus 1 for each matching weak rule."""
    strong, weak = adult_signals(text)
    return STRONG_WEIGHT * len(strong) + len(weak)


def is_adult_text(text: str, domain: str | None = None) -> bool:
    """Return True when the score of `text` reaches the threshold for `domain`."""
    return adult_score(text) >= MIN_SCORE.get(domain or "", DEFAULT_MIN_SCORE)


def _column(items: pd.DataFrame, name: str) -> pd.Series:
    if name not in items:
        return pd.Series("", index=items.index, dtype=object)
    return items[name].astype(object).where(items[name].notna(), "").astype(str)


def text_adult_signal(items: pd.DataFrame) -> pd.Series:
    """Return True where the title and synopsis reach the adult threshold for the row's domain."""
    text = _column(items, "title") + "\n" + _column(items, "synopsis")
    domains = _column(items, "domain")
    flags = [is_adult_text(t, d) for t, d in zip(text, domains, strict=True)]
    return pd.Series(flags, index=items.index, dtype=bool)


def refine_adult(items: pd.DataFrame) -> pd.Series:
    """Return the boolean `is_adult` flag: the existing flag OR the text signal. Keep the frame index.

    The frame needs `title` and `synopsis`. The optional `domain` column selects the threshold.
    A missing `is_adult` column counts as False.
    The function never clears an existing True flag.
    """
    if "is_adult" in items:
        existing = items["is_adult"].astype(object).where(items["is_adult"].notna(), False).astype(bool)
    else:
        existing = pd.Series(False, index=items.index, dtype=bool)
    return (existing | text_adult_signal(items)).rename("is_adult")
