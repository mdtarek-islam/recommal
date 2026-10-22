# ml-data-pipeline knowledge

Durable lessons for `ml-data-pipeline`. `/promote-memory` adds entries after user approval.

## Database facts (2026-10-22)

- `auth_utils.py` connects with psycopg2. It reads `user`, `password`, `host`, `port` and `dbname` from `.env`.
- It opens a new connection for each call. There is no pool.
- `siamese_recommendations` is read by column position: index 1 = chosen id, 2 = chosen title, 3 = recommendation domain, then 5 groups of 3 columns from index 4 (id at 4+3i, title at 5+3i).
- Title search uses `ILIKE '%title%' LIMIT 1` with no ordering, so the match is not deterministic.
- Anime details: `animes.synopsis` and `anime_main_pictures.large_url`.
- Game details: a `UNION ALL` over `steam_games_chunk_1` to `steam_games_chunk_10`, with `detailed_description` and `header_image`.
- `get_media_details` runs 1 to 2 queries for each item. That is an N+1 pattern over 6 items.
- No model, embedding or ingestion code exists in the repository.
