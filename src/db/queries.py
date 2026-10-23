"""Parameterised queries used by the Streamlit app. Read columns by name only."""

from __future__ import annotations

from typing import Any

from src.db.pool import execute, fetch_all, fetch_one

DOMAIN_TABLES = {"anime": "public.animes", "game": "public.steam_games"}
_YEAR_COLUMN = {"anime": "start_year", "game": "release_year"}


def _table(domain: str) -> str:
    try:
        return DOMAIN_TABLES[domain]
    except KeyError:
        raise ValueError(f"Unknown domain: {domain!r}") from None


def search_titles(domain: str, query: str, limit: int = 8, include_adult: bool = False) -> list[dict[str, Any]]:
    """Return title matches ranked by trigram similarity, then popularity. The order is deterministic."""
    table, year = _table(domain), _YEAR_COLUMN[domain]
    # Each LIKE predicate repeats its trigram index expression exactly (lower(title),
    # lower(alt_title)), so the planner can combine both GIN indexes with a BitmapOr.
    if domain == "anime":
        alt, match = "alt_title", "(lower(title) like %(pattern)s or lower(alt_title) like %(pattern)s)"
        rank = ("greatest(extensions.similarity(lower(title), %(q)s), "
                "coalesce(extensions.similarity(lower(alt_title), %(q)s), 0))")  # fmt: skip
    else:
        alt, match = "null::text", "lower(title) like %(pattern)s"
        rank = "extensions.similarity(lower(title), %(q)s)"
    sql = f"""
        select id, title, {alt} as alt_title, {year} as year, popularity
        from {table}
        where {match}
          and (%(adult)s or not is_adult)
        order by {rank} desc, popularity desc, id
        limit %(limit)s
    """  # noqa: S608 - table and column names come from fixed allow-lists above.
    q = query.strip().lower()
    escaped = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return fetch_all(sql, {"pattern": f"%{escaped}%", "q": q, "adult": include_adult, "limit": limit})


def get_item(domain: str, item_id: int) -> dict[str, Any] | None:
    year = _YEAR_COLUMN[domain]
    sql = f"""
        select id, title, synopsis, image_url, {year} as year, popularity, genres, themes
        from {_table(domain)} where id = %s
    """  # noqa: S608
    return fetch_one(sql, (item_id,))


def get_recommendations(domain: str, item_id: int, variant: str) -> list[dict[str, Any]]:
    """Return ranked recommendations with target details, in one query (no N+1).

    Drop adult targets unless the source item is adult. A missing source row counts as non-adult.
    Keep the stored rank order; the result can hold fewer rows than the stored list.
    """
    source_table = _table(domain)
    target = "game" if domain == "anime" else "anime"
    year = _YEAR_COLUMN[target]
    sql = f"""
        select u.rank::int as rank, u.score, u.target_id as id, t.title, t.synopsis, t.image_url,
               t.{year} as year, t.genres, t.themes
        from public.recommendations r
        cross join lateral unnest(r.target_ids, r.scores) with ordinality as u(target_id, score, rank)
        join {_table(target)} t on t.id = u.target_id
        left join {source_table} s on s.id = r.source_id
        where r.variant = %s and r.source_domain = %s and r.source_id = %s
          and (coalesce(s.is_adult, false) or not t.is_adult)
        order by u.rank
    """  # noqa: S608
    return fetch_all(sql, (variant, domain, item_id))


def get_user_hash(email: str) -> dict[str, Any] | None:
    return fetch_one("select email, password_hash from public.users where lower(email) = lower(%s)", (email,))


def insert_user(email: str, password_hash: str) -> None:
    execute("insert into public.users (email, password_hash) values (%s, %s)", (email, password_hash))


def insert_ab_event(event: dict[str, Any]) -> None:
    execute(
        """
        insert into public.ab_test_events
            (experiment, variant, user_hash, event_type, query, source_domain, source_id,
             rec_ids, target_id, relevance, metadata)
        values (%(experiment)s, %(variant)s, %(user_hash)s, %(event_type)s, %(query)s, %(source_domain)s,
                %(source_id)s, %(rec_ids)s, %(target_id)s, %(relevance)s, %(metadata)s)
        """,
        event,
    )


def count_recent_login_failures(email_hash: str, window_minutes: int) -> int:
    """Return failed attempts for this email hash inside the window, after its most recent success."""
    row = fetch_one(
        """
        select count(*) as failures
        from public.login_attempts
        where email_hash = %(h)s
          and not succeeded
          and attempted_at > greatest(
              now() - make_interval(mins => %(window)s),
              coalesce((select max(attempted_at) from public.login_attempts
                        where email_hash = %(h)s and succeeded), '-infinity'::timestamptz))
        """,
        {"h": email_hash, "window": window_minutes},
    )
    return int(row["failures"]) if row else 0


def record_login_attempt(email_hash: str, succeeded: bool, retention_hours: int) -> None:
    """Store one attempt and prune rows past the retention period, in one transaction."""
    execute(
        """
        with pruned as (
            delete from public.login_attempts where attempted_at < now() - make_interval(hours => %(keep)s)
        )
        insert into public.login_attempts (email_hash, succeeded) values (%(h)s, %(ok)s)
        """,
        {"h": email_hash, "ok": succeeded, "keep": retention_hours},
    )
