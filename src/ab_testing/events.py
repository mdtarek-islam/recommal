"""Log A/B experiment events. A logging failure never breaks the user interface."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Any

from psycopg2.extras import Json

from src.ab_testing.cohort import assign_variant, hash_user
from src.config import AB_EXPERIMENT
from src.db import queries

log = logging.getLogger(__name__)

MAX_QUERY_CHARS = 100  # Store at most this many characters of the search text.


def build_event(
    user_id: str,
    event_type: str,
    *,
    query: str | None = None,
    source_domain: str | None = None,
    source_id: int | None = None,
    rec_ids: Sequence[int] | None = None,
    target_id: int | None = None,
    relevance: int | None = None,
    metadata: dict[str, Any] | None = None,
    experiment: str = AB_EXPERIMENT,
) -> dict[str, Any]:
    """Return the event row. Store a hashed user id, never the email."""
    return {
        "experiment": experiment,
        "variant": assign_variant(user_id, experiment),
        "user_hash": hash_user(user_id),
        "event_type": event_type,
        "query": query[:MAX_QUERY_CHARS] if query else None,
        "source_domain": source_domain,
        "source_id": source_id,
        "rec_ids": list(rec_ids) if rec_ids is not None else None,
        "target_id": target_id,
        "relevance": relevance,
        "metadata": metadata or {},
    }


def log_event(user_id: str, event_type: str, **kwargs: Any) -> bool:
    """Write one event. Return False and log a warning when the write fails."""
    event = build_event(user_id, event_type, **kwargs)
    try:
        queries.insert_ab_event({**event, "metadata": Json(event["metadata"])})
    except Exception as exc:  # noqa: BLE001 - a telemetry failure must never break the UI.
        # Log the exception type only: driver messages can contain host names and user names.
        log.warning("A/B event write failed: %s/%s (%s)", event["experiment"], event_type, type(exc).__name__)
        return False
    return True
