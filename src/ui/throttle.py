"""Login attempt throttling held in Streamlit session state.

The state counts failures for the session and for each email pseudonym. It never holds a
password or an email address. A new browser session starts with a clean count, so this
throttle only slows a single session. A server-side throttle must back it up.
"""

from __future__ import annotations

import math
from typing import Any

FREE_ATTEMPTS = 5  # Failures allowed before the first wait.
BASE_WAIT_S = 30.0  # First wait. Each later failure doubles it.
MAX_WAIT_S = 900.0
MAX_TRACKED_EMAILS = 50  # Bound the per-session map. The session counter still applies.

SESSION_KEY = "__session__"


def new_state() -> dict[str, dict[str, float]]:
    """Return an empty throttle state for `st.session_state`."""
    return {}


def wait_for(failures: int) -> float:
    """Return the wait in seconds that follows `failures` consecutive failures."""
    if failures < FREE_ATTEMPTS:
        return 0.0
    return min(BASE_WAIT_S * 2 ** (failures - FREE_ATTEMPTS), MAX_WAIT_S)


def _counters(state: dict[str, Any], email_key: str) -> list[dict[str, float]]:
    keys = [SESSION_KEY] + ([email_key] if email_key else [])
    return [state[key] for key in keys if key in state]


def seconds_left(state: dict[str, Any], email_key: str, now: float) -> int:
    """Return the whole seconds the user must wait before the next attempt. Return 0 when free."""
    left = max((c["locked_until"] - now for c in _counters(state, email_key)), default=0.0)
    return math.ceil(left) if left > 0 else 0


def record_failure(state: dict[str, Any], email_key: str, now: float) -> None:
    """Count one failed attempt for the session and for the email pseudonym."""
    keys = [SESSION_KEY] + ([email_key] if email_key else [])
    for key in keys:
        if key not in state:
            if len(state) > MAX_TRACKED_EMAILS:
                continue
            state[key] = {"failures": 0.0, "locked_until": 0.0}
        counter = state[key]
        counter["failures"] += 1
        wait = wait_for(int(counter["failures"]))
        if wait:
            counter["locked_until"] = now + wait


def record_success(state: dict[str, Any], email_key: str) -> None:
    """Clear the counters after a successful login."""
    state.pop(SESSION_KEY, None)
    if email_key:
        state.pop(email_key, None)
