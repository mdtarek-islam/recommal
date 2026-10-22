# streamlit-ui-builder knowledge

Durable lessons for `streamlit-ui-builder`. `/promote-memory` adds entries after user approval.

## Current UI (2026-10-22)

- `app.py` routes between three views with session state: login, search, results.
- Session keys: `logged_in`, `user_email`, `search_query`, `search_domain` (`game` or `anime`).
- The results view shows one input item and up to 5 recommendation cards in `st.columns(5)`.
- `app.py` uses `use_container_width`. Check with context7 whether the installed Streamlit version deprecates it.
- `auth_utils.py` shows raw exception text in `st.error`. Replace it with a fixed message and a log entry.
- No A/B testing code exists yet.
