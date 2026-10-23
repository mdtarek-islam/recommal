# repo-scout knowledge

Durable lessons for `repo-scout`. `/promote-memory` adds entries after user approval.

## Repository map (2026-10-22)

- `app.py`, `src/ui/`, `src/ab_testing/`: Streamlit app and A/B flow. Owner: `streamlit-ui-ux`.
- `src/ingest/`, `src/db/`, `db/`, `auth_utils.py` DB calls: data layer. Owner: `data-db-optimiser`.
- `src/ml/`, `src/embeddings/`, `src/evaluation/`: model and metrics. Owner: `ml-research-architect`.
- `tests/`, `.github/`, `.claude/hooks/`, tool configs: Owner: `qa-cyber-ci-auditor`.
- `README.md`, `docs/`, `LOCAL_RUNBOOK.md` (gitignored): Owner: `academic-critic-docs`.
- `src/config.py` holds every path and hyperparameter.
- Generated, gitignored: `data/processed/`, `artefacts/`.

## Dissertation sources

- Export folder: `C:\Users\tarek\Downloads\recommal` (set `RECOMMAL_RAW_DIR` to it). Holds `sql/animes_db.sql`, `sql/steam_games.sql` (771 MB), `ai_pipeline.ipynb`, `main.md` (dissertation text).
- Never open `.env` or `DATA/N30-Joker/token.json` in that folder; they hold credentials.
- Skip files over 1 GB (`preprocessed_embeddings.csv`). The pipeline regenerates them.
