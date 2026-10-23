"""Cached data access for Streamlit. Cache shared catalogue reads only; never cache per-user data."""

from __future__ import annotations

from typing import Any

import streamlit as st
from psycopg2.pool import ThreadedConnectionPool

import auth_utils
from src.db import pool, queries


@st.cache_resource(show_spinner=False)
def db_pool() -> ThreadedConnectionPool:
    """Hold the process-wide connection pool for the lifetime of the Streamlit server."""
    return pool.get_pool()


@st.cache_data(ttl="1h", show_spinner=False, max_entries=2000)
def search_titles(domain: str, query: str) -> list[dict[str, Any]]:
    db_pool()
    return queries.search_titles(domain, query)


@st.cache_data(ttl="1h", show_spinner=False, max_entries=5000)
def results(domain: str, item_id: int, variant: str) -> dict[str, Any] | None:
    db_pool()
    return auth_utils.get_results_data(domain, item_id, variant)
