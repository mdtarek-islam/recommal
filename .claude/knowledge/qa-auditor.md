# qa-auditor knowledge

Durable lessons for `qa-auditor`. `/promote-memory` adds entries after user approval.

## Test baseline (2026-10-22)

- No tests, mypy configuration or ruff configuration exist. Report these checks as `SKIP`, not `PASS`.
- The app needs a live database for login and search. A boot check needs no database.
- Streamlit health endpoint: `http://localhost:8501/_stcore/health`.
- Hooks need `jq` on PATH. On Windows, winget installs it under `%LOCALAPPDATA%\Microsoft\WinGet\Packages\jqlang.jq_*`.
