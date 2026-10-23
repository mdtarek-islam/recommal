"""Thread-safe psycopg2 connection pool configured from the environment.

Credential lookup order for each setting: `DB_<NAME>` environment variable, then the same
key in `.env`, then the legacy lowercase key in `.env` (`user`, `password`, `host`, `port`,
`dbname`). The legacy keys are read from the file only: on Windows, `os.environ` is
case-insensitive, so `os.getenv("user")` returns the shell's USER variable instead.
"""

from __future__ import annotations

import logging
import os
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path
from typing import Any

import psycopg2
from dotenv import dotenv_values
from psycopg2.extensions import connection as PgConnection
from psycopg2.extensions import cursor as PgCursor
from psycopg2.extras import RealDictCursor
from psycopg2.pool import ThreadedConnectionPool

from src.config import PROJECT_ROOT, SETTINGS

log = logging.getLogger(__name__)

# psycopg2 keyword -> accepted variable names, preferred name first.
_ENV_NAMES = {
    "user": ("DB_USER",),
    "password": ("DB_PASSWORD",),
    "host": ("DB_HOST",),
    "port": ("DB_PORT",),
    "dbname": ("DB_NAME", "DB_DBNAME"),
}


class DatabaseUnavailable(RuntimeError):
    """Raised when credentials are missing or the database cannot be reached."""


@lru_cache(maxsize=1)
def _dotenv() -> dict[str, str | None]:
    path = Path(os.environ.get("RECOMMAL_ENV_FILE", PROJECT_ROOT / ".env"))
    return dotenv_values(path) if path.exists() else {}


def db_settings() -> dict[str, str]:
    """Return connection keyword arguments. Raise DatabaseUnavailable when a value is missing."""
    file_values = _dotenv()
    settings: dict[str, str] = {}
    for key, env_names in _ENV_NAMES.items():
        value = next((v for name in env_names if (v := os.environ.get(name) or file_values.get(name))), None)
        value = value or file_values.get(key)
        if not value:
            raise DatabaseUnavailable(f"Database setting {env_names[0]} is not configured.")
        settings[key] = value
    return settings


_pool: ThreadedConnectionPool | None = None
_pool_lock = threading.Lock()


def get_pool() -> ThreadedConnectionPool:
    """Return the process-wide pool. Create it on first use."""
    global _pool
    with _pool_lock:
        if _pool is None or _pool.closed:
            cfg = SETTINGS.database
            try:
                _pool = ThreadedConnectionPool(
                    cfg.pool_min, cfg.pool_max, connect_timeout=cfg.connect_timeout_s, sslmode="require",
                    application_name="recommal", **db_settings(),
                )  # fmt: skip
            except psycopg2.OperationalError as exc:
                raise DatabaseUnavailable("Cannot connect to the database.") from exc
        return _pool


def close_pool() -> None:
    global _pool
    with _pool_lock:
        if _pool is not None and not _pool.closed:
            _pool.closeall()
        _pool = None


@contextmanager
def connection() -> Iterator[PgConnection]:
    """Borrow a pooled connection. Commit on success, roll back on error, always return it."""
    pool = get_pool()
    conn = pool.getconn()
    broken = False
    try:
        yield conn
        conn.commit()
    except psycopg2.OperationalError:
        broken = True
        raise
    except Exception:
        conn.rollback()
        raise
    finally:
        pool.putconn(conn, close=broken or bool(conn.closed))


@contextmanager
def cursor() -> Iterator[PgCursor]:
    """Yield a RealDictCursor inside a pooled transaction. Rows are dictionaries keyed by column name."""
    with connection() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        yield cur


def fetch_all(sql: str, params: tuple[Any, ...] | dict[str, Any] | None = None) -> list[dict[str, Any]]:
    with cursor() as cur:
        cur.execute(sql, params)
        return [dict(row) for row in cur.fetchall()]


def fetch_one(sql: str, params: tuple[Any, ...] | dict[str, Any] | None = None) -> dict[str, Any] | None:
    with cursor() as cur:
        cur.execute(sql, params)
        row = cur.fetchone()
        return dict(row) if row else None


def execute(sql: str, params: tuple[Any, ...] | dict[str, Any] | None = None) -> int:
    with cursor() as cur:
        cur.execute(sql, params)
        return int(cur.rowcount)
