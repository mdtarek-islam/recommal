"""URL state for the search flow.

The URL holds the domain and the chosen title id, so refresh, browser Back and Forward,
and shared links reopen the same view. Streamlit adds a browser history entry each time
the app writes `st.query_params`, and reruns the script when the user moves through history.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from src.config import DOMAINS

DOMAIN_PARAM = "domain"
ID_PARAM = "id"
_MAX_ID_DIGITS = 10


class QueryParams(Protocol):
    """The subset of `st.query_params` that this module uses."""

    def get(self, key: str, /) -> str | None: ...

    def from_dict(self, params: Mapping[str, Any]) -> None: ...


@dataclass(frozen=True)
class Route:
    """The view that the URL requests. `invalid` is True when the URL holds a bad value."""

    domain: str | None = None
    item_id: int | None = None
    invalid: bool = False


def _parse_id(raw: str) -> int | None:
    if not raw.isascii() or not raw.isdigit() or len(raw) > _MAX_ID_DIGITS:
        return None
    value = int(raw)
    return value if value > 0 else None


def read(params: QueryParams) -> Route:
    """Return the route that the query parameters request. Ignore and flag bad values."""
    raw_domain = params.get(DOMAIN_PARAM)
    raw_id = params.get(ID_PARAM)
    domain = raw_domain if raw_domain in DOMAINS else None
    invalid = raw_domain is not None and domain is None
    if raw_id is None:
        return Route(domain=domain, invalid=invalid)
    item_id = _parse_id(str(raw_id))
    if item_id is None or domain is None:
        return Route(domain=domain, invalid=True)
    return Route(domain=domain, item_id=item_id, invalid=invalid)


def write_search(params: QueryParams, domain: str) -> None:
    """Point the URL at the search view for one domain."""
    params.from_dict({DOMAIN_PARAM: domain})


def write_results(params: QueryParams, domain: str, item_id: int) -> None:
    """Point the URL at the results view for one title."""
    params.from_dict({DOMAIN_PARAM: domain, ID_PARAM: str(int(item_id))})
