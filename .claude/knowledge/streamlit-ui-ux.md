# streamlit-ui-ux knowledge

Durable lessons for `streamlit-ui-ux`. `/promote-memory` adds entries after user approval.

## Current UI (2026-10-22)

- Views: login, search (domain segmented control, title search, match buttons), results (input item and 5 cards).
- A/B experiment `rec_layout_v1`: `control` shows plain cards ranked by latent similarity; `explained` ranks with a popularity prior and shows a match badge and shared themes.
- `st.feedback` uses `on_change`, so a vote logs once; `logged_feedback` in session state is a second guard.
- Streamlit 1.66 uses `width="stretch"`; `use_container_width` is deprecated.
- The app boots and shows the login page with no database credentials.
