"""Deterministic, stateless cohort assignment.

A user receives the same variant on every visit and device, with no stored assignment.
Telemetry stores an HMAC-SHA256 pseudonym keyed by `RECOMMAL_AB_SALT`, never an email address.
Production must set `RECOMMAL_AB_SALT` to a long random secret. Without it, the module logs one
warning and uses a public development key, so the pseudonym gives no protection.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
import threading

from src.config import AB_EXPERIMENT, AB_VARIANTS

log = logging.getLogger(__name__)

# Public development key. It is also the historic salt, so bucket assignment stays unchanged.
_DEV_SALT = "recommal-ab"
_warned = False
_warn_lock = threading.Lock()


def _salt() -> str:
    """Return the configured key. Log one warning when the development key is in use."""
    global _warned
    salt = os.environ.get("RECOMMAL_AB_SALT")
    if salt:
        return salt
    with _warn_lock:
        if not _warned:
            log.warning("RECOMMAL_AB_SALT is not set. The A/B pseudonym uses the public development key.")
            _warned = True
    return _DEV_SALT


def _normalise(user_id: str) -> str:
    return user_id.strip().lower()


def hash_user(user_id: str) -> str:
    """Return a keyed HMAC-SHA256 pseudonym for a user identifier."""
    return hmac.new(_salt().encode(), _normalise(user_id).encode(), hashlib.sha256).hexdigest()


def _bucket_key(user_id: str) -> str:
    """Return the bucketing key. Keep this derivation fixed so live users keep their variant.

    The value never leaves this module and is never stored.
    """
    return hashlib.sha256(f"{_salt()}:{_normalise(user_id)}".encode()).hexdigest()


def assign_variant(user_id: str, experiment: str = AB_EXPERIMENT, variants: tuple[str, ...] = AB_VARIANTS) -> str:
    """Return the variant for this user and experiment. Each variant receives an equal share."""
    if not variants:
        raise ValueError("variants must not be empty")
    digest = hashlib.sha256(f"{experiment}:{_bucket_key(user_id)}".encode()).digest()
    bucket = int.from_bytes(digest[:8], "big") % len(variants)
    return variants[bucket]
