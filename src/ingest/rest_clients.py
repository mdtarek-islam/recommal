"""Rate-limited REST clients for the MyAnimeList v2 API and the Steam Store API.

Both APIs are free. MyAnimeList needs a client ID from https://myanimelist.net/apiconfig,
read from the MAL_CLIENT_ID environment variable. The Steam Store API needs no key.
"""

from __future__ import annotations

import logging
import os
import random
import time
from collections.abc import Callable
from typing import Any

import requests

log = logging.getLogger(__name__)

RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})


class ApiError(RuntimeError):
    """Raised when an API call fails after all retries."""


def backoff_delay(attempt: int, base: float = 1.0, cap: float = 60.0, retry_after: str | None = None) -> float:
    """Return the wait in seconds before retry `attempt` (1-based).

    Respect a numeric Retry-After header. Otherwise use exponential backoff with full jitter.
    """
    if retry_after:
        try:
            return min(cap, max(0.0, float(retry_after)))
        except ValueError:
            pass
    return random.uniform(0, min(cap, base * 2 ** (attempt - 1)))


class RestClient:
    """HTTP GET client with retries, exponential backoff, jitter and a minimum request interval."""

    def __init__(
        self,
        base_url: str,
        headers: dict[str, str] | None = None,
        min_interval_s: float = 1.0,
        max_attempts: int = 5,
        timeout_s: float = 20.0,
        session: requests.Session | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.session = session or requests.Session()
        self.session.headers.update(headers or {})
        self.min_interval_s = min_interval_s
        self.max_attempts = max_attempts
        self.timeout_s = timeout_s
        self._sleep = sleep
        self._last_call = 0.0

    def get_json(self, path: str, params: dict[str, Any] | None = None) -> Any:
        url = f"{self.base_url}/{path.lstrip('/')}"
        for attempt in range(1, self.max_attempts + 1):
            wait = self.min_interval_s - (time.monotonic() - self._last_call)
            if wait > 0:
                self._sleep(wait)
            self._last_call = time.monotonic()
            try:
                response = self.session.get(url, params=params, timeout=self.timeout_s)
            except requests.RequestException as exc:
                if attempt == self.max_attempts:
                    raise ApiError(f"GET {url} failed: {exc}") from exc
                delay = backoff_delay(attempt)
                log.warning("GET %s network error (attempt %d); retry in %.1fs", url, attempt, delay)
                self._sleep(delay)
                continue
            if response.status_code in RETRY_STATUSES and attempt < self.max_attempts:
                delay = backoff_delay(attempt, retry_after=response.headers.get("Retry-After"))
                log.warning("GET %s HTTP %d (attempt %d); retry in %.1fs", url, response.status_code, attempt, delay)
                self._sleep(delay)
                continue
            if not response.ok:
                raise ApiError(f"GET {url} returned HTTP {response.status_code}")
            return response.json()
        raise ApiError(f"GET {url} failed after {self.max_attempts} attempts")


MAL_FIELDS = "id,title,alternative_titles,start_date,synopsis,genres,media_type,rating,num_list_users,main_picture"


def mal_client() -> RestClient:
    client_id = os.environ.get("MAL_CLIENT_ID")
    if not client_id:
        raise ApiError("Set MAL_CLIENT_ID to call the MyAnimeList API.")
    return RestClient("https://api.myanimelist.net/v2", headers={"X-MAL-CLIENT-ID": client_id})


def fetch_mal_anime(client: RestClient, anime_id: int) -> dict[str, Any]:
    """Return one anime record from the MyAnimeList v2 API."""
    data: dict[str, Any] = client.get_json(f"anime/{anime_id}", params={"fields": MAL_FIELDS})
    return data


def steam_client() -> RestClient:
    # The Steam Store API allows about 200 requests in 5 minutes.
    return RestClient("https://store.steampowered.com/api", min_interval_s=1.5)


def fetch_steam_app(client: RestClient, appid: int) -> dict[str, Any] | None:
    """Return the Steam appdetails payload for one app, or None when Steam has no data."""
    payload = client.get_json("appdetails", params={"appids": appid, "l": "english"})
    entry = payload.get(str(appid), {}) if isinstance(payload, dict) else {}
    return entry.get("data") if entry.get("success") else None
