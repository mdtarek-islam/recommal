---
name: streamlit-ui-polish
description: Layout, accessibility, state and performance rules for the Recommal Streamlit app. Use before you change app.py, src/ui/ or src/ab_testing/.
---

# Streamlit UI polish

## Layout

1. Use `layout="wide"` and cap content width with CSS on `.block-container`.
2. Use `st.columns` with the default `wrap=True`, so columns stack at mobile width (375px).
3. Give card images one fixed aspect ratio with `object-fit: cover`.
4. Use `width="stretch"`. `use_container_width` is deprecated.
5. Check each view at 1440px and at 375px.

## Accessibility

1. Give every input a visible label. Do not use a placeholder as the only label.
2. Do not use colour as the only signal. Pair each badge colour with text.
3. Escape all data with `html.escape` before `unsafe_allow_html=True`.
4. Keep controls usable with the keyboard. Prefer native widgets to custom HTML.

## State and flow

1. Initialise every `st.session_state` key in one block at the top of `app.py`.
2. Change state in callbacks (`on_click`), then let Streamlit rerun.
3. Deduplicate events that rerun can repeat, such as `st.feedback` values.
4. Show an empty state, a loading state and an error state for each data view.
5. Show a fixed error message. Log the exception; never show its text.

## Performance

1. Cache shared reads with `@st.cache_data(ttl=...)`.
2. Hold the connection pool with `@st.cache_resource`.
3. Never cache per-user data with `@st.cache_resource`.
4. Fetch a view's data in one query. Avoid N+1 queries.

## A/B testing

1. Assign the variant with `assign_variant()`. Never store the assignment.
2. Log one exposure for each (item, variant, session).
3. Store a hashed user id only.
