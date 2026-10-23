"""Stream rows from PostgreSQL `pg_dump` files that use the COPY text format.

The dissertation stored the raw MyAnimeList and Steam API responses in PostgreSQL.
This module reads those dumps without a database server and with constant memory.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Iterator
from pathlib import Path

_ESCAPES = {"b": "\b", "f": "\f", "n": "\n", "r": "\r", "t": "\t", "v": "\v", "\\": "\\"}
_ESCAPE_RE = re.compile(r"\\(x[0-9A-Fa-f]{1,2}|[0-7]{1,3}|.)")


def _unescape(match: re.Match[str]) -> str:
    token = match.group(1)
    if token in _ESCAPES:
        return _ESCAPES[token]
    if token[0] == "x":
        return chr(int(token[1:], 16))
    if token[0].isdigit():
        return chr(int(token, 8))
    return token


def decode_field(raw: str) -> str | None:
    """Decode one COPY text-format field. Return None for SQL NULL."""
    if raw == "\\N":
        return None
    if "\\" not in raw:
        return raw
    return _ESCAPE_RE.sub(_unescape, raw)


_HEADER_RE = re.compile(r"^COPY public\.(?P<table>\w+) \((?P<cols>[^)]*)\) FROM stdin;$")

Row = dict[str, str | None]


def iter_copy_tables(path: Path, tables: Iterable[str]) -> Iterator[tuple[str, Row]]:
    """Yield `(table, row)` for each COPY row of the requested tables, in one pass over `path`."""
    wanted = set(tables)
    found: set[str] = set()
    table: str | None = None
    columns: list[str] = []
    with path.open(encoding="utf-8", newline="\n") as handle:
        for line in handle:
            line = line.rstrip("\n")
            if table is None:
                match = _HEADER_RE.match(line)
                if match and match.group("table") in wanted:
                    table = match.group("table")
                    columns = [c.strip() for c in match.group("cols").split(",")]
                    found.add(table)
                continue
            if line == "\\.":
                table = None
                if found == wanted:
                    break
                continue
            fields = line.split("\t")
            if len(fields) != len(columns):
                raise ValueError(f"{path.name}:{table}: expected {len(columns)} fields, found {len(fields)}")
            yield table, {col: decode_field(val) for col, val in zip(columns, fields, strict=True)}
    missing = wanted - found
    if missing:
        raise KeyError(f"Tables {sorted(missing)} not found in {path}")


def iter_copy_rows(path: Path, table: str) -> Iterator[Row]:
    """Yield each row of `COPY public.<table>` in `path` as a column-name dictionary."""
    for _, row in iter_copy_tables(path, [table]):
        yield row
