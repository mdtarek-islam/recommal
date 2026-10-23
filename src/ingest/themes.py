"""Canonical cross-domain theme taxonomy.

MyAnimeList genres describe themes. Steam genres describe gameplay. This module maps both
vocabularies into one canonical theme set, which serves as weak, embedding-independent
ground truth for training pairs and for MAP@K evaluation.

Anime themes come from curated MAL genre labels. Game themes come from Steam genres plus a
fixed keyword lexicon over the game description. A lexicon theme needs at least
`MIN_KEYWORD_HITS` distinct keyword matches, which limits false positives from single words.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

THEMES: tuple[str, ...] = (
    "action", "adventure", "comedy", "crime", "drama", "fantasy", "historical", "horror",
    "martial_arts", "mecha", "military", "music", "mystery", "psychological", "racing",
    "romance", "school", "sci_fi", "slice_of_life", "sports", "strategy", "supernatural",
    "survival",
)  # fmt: skip

ANIME_GENRE_THEMES: dict[str, tuple[str, ...]] = {
    "Action": ("action",),
    "Adventure": ("adventure",),
    "Comedy": ("comedy",),
    "Gag Humor": ("comedy",),
    "Parody": ("comedy",),
    "Drama": ("drama",),
    "Fantasy": ("fantasy",),
    "Urban Fantasy": ("fantasy", "supernatural"),
    "Mythology": ("fantasy",),
    "Isekai": ("fantasy", "adventure"),
    "Mahou Shoujo": ("fantasy",),
    "Sci-Fi": ("sci_fi",),
    "Space": ("sci_fi",),
    "Time Travel": ("sci_fi",),
    "Mecha": ("mecha", "sci_fi"),
    "Horror": ("horror",),
    "Gore": ("horror",),
    "Mystery": ("mystery",),
    "Detective": ("mystery", "crime"),
    "Suspense": ("mystery",),
    "Romance": ("romance",),
    "Love Polygon": ("romance",),
    "Love Status Quo": ("romance",),
    "Harem": ("romance",),
    "Reverse Harem": ("romance",),
    "Girls Love": ("romance",),
    "Boys Love": ("romance",),
    "Slice of Life": ("slice_of_life",),
    "Iyashikei": ("slice_of_life",),
    "CGDCT": ("slice_of_life",),
    "Gourmet": ("slice_of_life",),
    "Workplace": ("slice_of_life",),
    "Childcare": ("slice_of_life",),
    "Pets": ("slice_of_life",),
    "Sports": ("sports",),
    "Team Sports": ("sports",),
    "Combat Sports": ("sports", "martial_arts"),
    "Racing": ("racing",),
    "Music": ("music",),
    "Idols (Female)": ("music",),
    "Idols (Male)": ("music",),
    "Performing Arts": ("music",),
    "Showbiz": ("music",),
    "Military": ("military",),
    "Historical": ("historical",),
    "Samurai": ("historical", "martial_arts"),
    "Supernatural": ("supernatural",),
    "Vampire": ("supernatural", "horror"),
    "Super Power": ("supernatural", "action"),
    "Reincarnation": ("supernatural",),
    "Psychological": ("psychological",),
    "Martial Arts": ("martial_arts",),
    "School": ("school",),
    "Delinquents": ("school", "crime"),
    "Survival": ("survival",),
    "Strategy Game": ("strategy",),
    "High Stakes Game": ("strategy", "psychological"),
    "Organized Crime": ("crime",),
}

STEAM_GENRE_THEMES: dict[str, tuple[str, ...]] = {
    "Action": ("action",),
    "Adventure": ("adventure",),
    "Strategy": ("strategy",),
    "Racing": ("racing",),
    "Sports": ("sports",),
    "Gore": ("horror",),
}

ADULT_ANIME_GENRES = frozenset({"Hentai", "Erotica"})
ADULT_STEAM_GENRES = frozenset({"Sexual Content", "Nudity"})
NON_GAME_STEAM_GENRES = frozenset({
    "Audio Production", "Design & Illustration", "Education", "Software Training", "Utilities",
    "Accounting", "Animation & Modeling", "Video Production", "Game Development",
    "Web Publishing", "Photo Editing", "Movie", "Documentary", "Episodic", "Short",
    "Tutorial", "360 Video",
})  # fmt: skip

_KEYWORDS: dict[str, tuple[str, ...]] = {
    "comedy": (r"comedy", r"comedic", r"funny", r"hilarious", r"humou?r\w*", r"parody", r"wacky", r"silly"),
    "crime": (r"crime\w*", r"criminals?", r"mafia", r"gangsters?", r"heists?", r"yakuza", r"thie(f|ves)",
              r"outlaws?", r"bount(y|ies)", r"detectives?"),
    "drama": (r"drama\w*", r"tragedy", r"tragic", r"heartbreak\w*", r"emotional stor(y|ies)", r"grief"),
    "fantasy": (r"fantasy", r"magic\w*", r"wizards?", r"sorcer\w+", r"dragons?", r"elves", r"elf", r"dwarf\w*",
                r"enchant\w*", r"spells?", r"mythic\w*", r"kingdoms?", r"knights?"),
    "historical": (r"historical", r"medieval", r"ancient", r"feudal", r"samurai", r"shogun\w*", r"victorian",
                   r"vikings?", r"roman empire", r"world war", r"ww(ii|2)", r"ninjas?"),
    "horror": (r"horror", r"terrif\w+", r"zombies?", r"haunted", r"nightmares?", r"creepy", r"gore", r"gruesome",
               r"demons?", r"undead", r"eldritch", r"dread"),
    "martial_arts": (r"martial arts?", r"kung fu", r"karate", r"fighting game", r"brawler", r"boxing",
                     r"wrestl\w+", r"sword fight\w*", r"samurai", r"ninjas?"),
    "mecha": (r"mecha", r"mechs?", r"giant robots?", r"exosuits?", r"battle suits?"),
    "military": (r"military", r"army", r"armies", r"soldiers?", r"warfare", r"tanks?", r"battlefield",
                 r"troops", r"squad\w*", r"world war", r"commander"),
    "music": (r"music\w*", r"rhythm", r"songs?", r"bands?", r"idols?", r"concerts?", r"danc\w+", r"beats?"),
    "mystery": (r"myster\w+", r"detectives?", r"investigat\w+", r"clues?", r"murders?", r"secrets?",
                r"conspirac\w+", r"whodunit"),
    "psychological": (r"psychological", r"sanity", r"madness", r"existential", r"trauma\w*", r"paranoi\w+",
                      r"mind games?", r"insanity"),
    "romance": (r"romanc\w+", r"romantic", r"love stor(y|ies)", r"dating", r"otome", r"girlfriends?",
                r"boyfriends?", r"fall in love", r"relationships?"),
    "school": (r"school\w*", r"students?", r"classmates?", r"academy", r"teachers?", r"campus", r"club room"),
    "sci_fi": (r"sci-?fi", r"science fiction", r"space ?ships?", r"galax\w+", r"aliens?", r"futuristic",
               r"cyberpunk", r"robots?", r"planets?", r"interstellar", r"time travel", r"starships?", r"androids?"),
    "slice_of_life": (r"slice of life", r"cozy", r"cosy", r"relaxing", r"farm\w*", r"cooking", r"daily life",
                      r"wholesome", r"caf[eé]s?", r"everyday life", r"life sim\w*"),
    "supernatural": (r"supernatural", r"ghosts?", r"spirits?", r"vampires?", r"curse[ds]?", r"occult",
                     r"paranormal", r"psychic\w*", r"super ?powers?", r"youkai", r"yokai"),
    "survival": (r"survival", r"surviv\w+", r"post-apocalyptic", r"apocalyp\w+", r"stranded", r"scaveng\w+"),
    "strategy": (r"strateg\w+", r"tactic\w*", r"turn-based", r"chess", r"card games?", r"deck-?build\w*",
                 r"gambl\w+", r"poker"),
}  # fmt: skip

MIN_KEYWORD_HITS = 2

_KEYWORD_PATTERNS: dict[str, list[re.Pattern[str]]] = {
    theme: [re.compile(rf"\b{kw}\b", re.IGNORECASE) for kw in words] for theme, words in _KEYWORDS.items()
}


def _from_genres(genres: Iterable[str], mapping: dict[str, tuple[str, ...]]) -> set[str]:
    themes: set[str] = set()
    for genre in genres:
        themes.update(mapping.get(genre, ()))
    return themes


def anime_themes(genres: Iterable[str]) -> list[str]:
    """Map MyAnimeList genre names to sorted canonical themes."""
    return sorted(_from_genres(genres, ANIME_GENRE_THEMES))


def keyword_themes(text: str) -> set[str]:
    """Return themes with at least MIN_KEYWORD_HITS distinct keyword matches in `text`."""
    found: set[str] = set()
    for theme, patterns in _KEYWORD_PATTERNS.items():
        hits = sum(1 for pattern in patterns if pattern.search(text))
        if hits >= MIN_KEYWORD_HITS:
            found.add(theme)
    return found


def game_themes(genres: Iterable[str], text: str) -> list[str]:
    """Map Steam genre names and description keywords to sorted canonical themes."""
    return sorted(_from_genres(genres, STEAM_GENRE_THEMES) | keyword_themes(text))


def jaccard(a: Iterable[str], b: Iterable[str]) -> float:
    """Return the Jaccard similarity of two theme collections. Return 0.0 when both are empty."""
    sa, sb = set(a), set(b)
    union = sa | sb
    return len(sa & sb) / len(union) if union else 0.0
