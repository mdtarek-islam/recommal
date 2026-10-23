from src.ingest.clean import (
    NO_SYNOPSIS,
    clean_synopsis,
    clean_title,
    merge_descriptions,
    normalise_title,
    strip_broken_chars,
    truncate,
)


def test_clean_synopsis_strips_markup_and_entities() -> None:
    raw = "<p>Spike &amp; Jet<br/>hunt <b>bounties</b>.</p><img src='x.png'><script>alert(1)</script>"
    assert clean_synopsis(raw) == "Spike & Jet\nhunt\nbounties\n."


def test_clean_synopsis_removes_mal_boilerplate() -> None:
    assert clean_synopsis("A bounty hunter story. [Written by MAL Rewrite]") == "A bounty hunter story."


def test_clean_synopsis_handles_empty_input() -> None:
    assert clean_synopsis(None) == NO_SYNOPSIS
    assert clean_synopsis("   ") == NO_SYNOPSIS
    assert clean_synopsis("<div></div>") == NO_SYNOPSIS


def test_merge_descriptions_drops_contained_duplicates() -> None:
    short = "Fight dragons."
    long = "<p>Fight dragons. Build a kingdom.</p>"
    assert merge_descriptions(short, long, None) == "Fight dragons. Build a kingdom."


def test_merge_descriptions_keeps_distinct_fields_in_order() -> None:
    assert merge_descriptions("First part.", "Second part.") == "First part.\nSecond part."


def test_truncate_cuts_at_word_boundary() -> None:
    assert truncate("one two three four", 9) == "one two..."
    assert truncate("short", 10) == "short"


def test_normalise_title_folds_case_and_accents() -> None:
    assert normalise_title("Pokémon: Red & Blue!") == "pokemon red blue"


def test_clean_title_strips_replacement_and_control_chars() -> None:
    assert clean_title("Sekiro�") == "Sekiro"
    assert clean_title("Cowboy\x00 Bebop\x1f\u0085") == "Cowboy Bebop"
    assert clean_title(" Two\n\tLines ") == "Two Lines"
    assert clean_title("Pokémon™") == "Pokémon™"
    assert clean_title("�\x07") is None
    assert clean_title(None) is None


def test_strip_broken_chars_keeps_line_breaks() -> None:
    assert strip_broken_chars("One�.\r\nTwo\x0b.") == "One.\nTwo."
    assert strip_broken_chars(None) is None
