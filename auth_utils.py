"""Authentication and results helpers for the Streamlit app.

This module keeps the public API of the dissertation prototype. Database access lives in
`src.db`; text cleaning lives in `src.ingest.clean`.
"""

from __future__ import annotations

import logging
import re
import threading
import time
from typing import Any

import bcrypt
import psycopg2
from psycopg2 import errors as pg_errors

from src.ab_testing.cohort import hash_user
from src.db import queries
from src.db.pool import DatabaseUnavailable
from src.ingest.clean import clean_synopsis

__all__ = [
    "check_password",
    "clean_synopsis",
    "get_results_data",
    "hash_password",
    "login_user",
    "register_user",
    "validate_credentials",
]

log = logging.getLogger(__name__)

MIN_PASSWORD_LENGTH = 8
MAX_PASSWORD_BYTES = 72  # bcrypt ignores or rejects input beyond 72 bytes.
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

DB_ERROR = "The service is not available. Try again later."
LOGIN_ERROR = "Incorrect email or password."
THROTTLE_ERROR = "Too many attempts. Try again later."
REGISTER_MESSAGE = "If this email can be registered, check your details and log in."

MAX_FAILED_ATTEMPTS = 5
THROTTLE_WINDOW_MINUTES = 15
ATTEMPT_RETENTION_HOURS = 24
_THROTTLE_RETRY_S = 600.0  # Time before a retry when public.login_attempts is missing.

_throttle_lock = threading.Lock()
_throttle_missing_since: float | None = None
_throttle_warned = False


def hash_password(password: str) -> str:
    """Return a bcrypt hash with a random salt."""
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def check_password(hashed_password: str, user_password: str) -> bool:
    """Return True when the password matches the stored hash."""
    try:
        return bcrypt.checkpw(user_password.encode("utf-8"), hashed_password.encode("utf-8"))
    except ValueError:
        return False


# Fixed hash for timing equalisation. The input is a public constant, not a secret.
_DUMMY_HASH = hash_password("recommal-timing-dummy")


def validate_credentials(email: str, password: str) -> str | None:
    """Return an error message, or None when the email and password are acceptable."""
    if not email or not password:
        return "Email and password are required."
    if not _EMAIL_RE.match(email.strip()):
        return "Enter a valid email address."
    if len(password) < MIN_PASSWORD_LENGTH:
        return f"Use a password with at least {MIN_PASSWORD_LENGTH} characters."
    if len(password.encode("utf-8")) > MAX_PASSWORD_BYTES:
        return f"Use a password of at most {MAX_PASSWORD_BYTES} bytes."
    return None


def register_user(email: str, password: str) -> tuple[bool, str]:
    """Create an account. Return one message for new and existing emails, so the result reveals no accounts."""
    error = validate_credentials(email, password)
    if error:
        return False, error
    try:
        queries.insert_user(email.strip(), hash_password(password))
    except psycopg2.IntegrityError:
        log.info("register_user: duplicate email")
    except (DatabaseUnavailable, psycopg2.Error) as exc:
        # Log the type only: driver messages can contain host or user names.
        log.error("register_user failed: %s", type(exc).__name__)
        return False, DB_ERROR
    return True, REGISTER_MESSAGE


def _throttle_enabled() -> bool:
    with _throttle_lock:
        if _throttle_missing_since is None:
            return True
        return time.monotonic() - _throttle_missing_since >= _THROTTLE_RETRY_S


def _mark_throttle_missing() -> None:
    """Disable the server-side throttle for a while. Log a warning once per process."""
    global _throttle_missing_since, _throttle_warned
    with _throttle_lock:
        _throttle_missing_since = time.monotonic()
        warn, _throttle_warned = not _throttle_warned, True
    if warn:
        log.warning("Table public.login_attempts is missing. Apply migration 002. Login throttling is off.")


def _mark_throttle_present() -> None:
    global _throttle_missing_since
    with _throttle_lock:
        _throttle_missing_since = None


def _is_throttled(email_hash: str) -> bool:
    """Return True when the email hash has too many recent failures. Raise on database errors."""
    if not _throttle_enabled():
        return False
    try:
        failures = queries.count_recent_login_failures(email_hash, THROTTLE_WINDOW_MINUTES)
    except pg_errors.UndefinedTable:
        _mark_throttle_missing()
        return False
    _mark_throttle_present()
    return failures >= MAX_FAILED_ATTEMPTS


def _record_attempt(email_hash: str, succeeded: bool) -> None:
    """Store the attempt. A failure here never blocks the login result."""
    if not _throttle_enabled():
        return
    try:
        queries.record_login_attempt(email_hash, succeeded, ATTEMPT_RETENTION_HOURS)
    except pg_errors.UndefinedTable:
        _mark_throttle_missing()
    except (DatabaseUnavailable, psycopg2.Error) as exc:
        # Log the type only: driver messages can contain host and user names.
        log.warning("record_login_attempt failed (%s)", type(exc).__name__)


def login_user(email: str, password: str) -> tuple[bool, str]:
    if not email or not password:
        return False, "Enter your email and password."
    email_hash = hash_user(email)
    try:
        # Check the throttle before bcrypt. The message is the same for known and unknown emails.
        if _is_throttled(email_hash):
            return False, THROTTLE_ERROR
        row = queries.get_user_hash(email.strip())
    except (DatabaseUnavailable, psycopg2.Error) as exc:
        log.error("login_user failed: %s", type(exc).__name__)
        return False, DB_ERROR
    if row is None:
        # Run bcrypt anyway so response time does not reveal unknown emails.
        check_password(_DUMMY_HASH, password)
        ok = False
    else:
        ok = check_password(row["password_hash"], password)
    _record_attempt(email_hash, ok)
    return (True, "Login successful.") if ok else (False, LOGIN_ERROR)


def get_results_data(domain: str, item_id: int, variant: str) -> dict[str, Any] | None:
    """Return the input item and its ranked recommendations, or None when the item is missing."""
    item = queries.get_item(domain, item_id)
    if item is None:
        return None
    return {
        "input_item": item,
        "recommendations": queries.get_recommendations(domain, item_id, variant),
        "rec_domain": "game" if domain == "anime" else "anime",
    }
