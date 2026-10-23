"""Recommal Streamlit entry point: cross-domain anime and game recommendations.

Run: streamlit run app.py
"""

from __future__ import annotations

import copy
import logging
import time
from typing import Any

import psycopg2
import streamlit as st

from auth_utils import DB_ERROR, LOGIN_ERROR, login_user, register_user
from src.ab_testing.cohort import assign_variant, hash_user
from src.ab_testing.events import log_event
from src.config import DOMAINS
from src.db.pool import DatabaseUnavailable
from src.ui import components, data, routing, throttle

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
for _noisy in ("psycopg2", "urllib3"):
    logging.getLogger(_noisy).setLevel(logging.WARNING)
log = logging.getLogger("recommal.app")

st.set_page_config(page_title="Recommal", page_icon="logo.png", layout="wide")
components.apply_styles()

MAX_RECENT = 5
MAX_QUERY_CHARS = 100  # Longer search text adds no precision to a title match.

# ---- Session state: initialise every key here and nowhere else.
DEFAULT_STATE: dict[str, Any] = {
    "logged_in": False,
    "user_email": "",  # Held in server memory for cohort assignment only. Never logged.
    "last_domain": "anime",  # Domain of the last search. Survives the results view.
    "last_query": "",  # Search text of the last search. Survives the results view.
    "domain_picker": "anime",  # Widget key. Synced from last_domain before each render.
    "query_input": "",  # Widget key. Synced from last_query before each render.
    "recent": [],  # Recently opened titles for this session: (domain, id, title), newest first.
    "login_throttle": throttle.new_state(),  # Failure counters. No passwords, no emails.
    "logged_exposures": set(),
    "logged_feedback": set(),
    "scroll_to_top": False,  # Set when a title opens; the next run scrolls the page to the top once.
}
for _key, _value in DEFAULT_STATE.items():
    if _key not in st.session_state:
        st.session_state[_key] = copy.deepcopy(_value)

DB_FAILURES = (DatabaseUnavailable, psycopg2.Error)


def log_failure(context: str, exc: BaseException) -> None:
    """Log the exception type only. Driver messages can hold host names and user names."""
    log.error("%s failed: %s", context, type(exc).__name__)


# ---- Callbacks. Each one changes state; Streamlit then reruns the script.
def on_domain_change() -> None:
    domain = st.session_state["domain_picker"]
    if domain in DOMAINS:
        st.session_state["last_domain"] = domain
        routing.write_search(st.query_params, domain)


def on_query_change() -> None:
    st.session_state["last_query"] = str(st.session_state["query_input"] or "")


def open_title(domain: str, item_id: int, via: str, query: str | None = None, **metadata: Any) -> None:
    """Open the results view for one title and log the search event."""
    st.session_state["last_domain"] = domain
    st.session_state["scroll_to_top"] = True
    routing.write_results(st.query_params, domain, item_id)
    log_event(st.session_state["user_email"], "search", query=query, source_domain=domain, source_id=item_id,
              metadata={"via": via, **metadata})  # fmt: skip


def back_to_search(domain: str) -> None:
    routing.write_search(st.query_params, domain)


def log_out() -> None:
    for key, value in DEFAULT_STATE.items():
        if key != "login_throttle":
            st.session_state[key] = copy.deepcopy(value)
    st.query_params.clear()


def remember_recent(domain: str, item_id: int, title: str) -> None:
    recent = [r for r in st.session_state["recent"] if (r[0], r[1]) != (domain, item_id)]
    st.session_state["recent"] = [(domain, item_id, title), *recent][:MAX_RECENT]


# ---- Views
def show_login_page() -> None:
    with st.container(key="login-card", border=True):
        st.image("logo.png", width=56, alt="Recommal logo")
        st.title("Recommal")
        st.write("Get game recommendations from an anime you like, or anime recommendations from a game.")
        login_tab, signup_tab = st.tabs(["Log in", "Create account"])
        with login_tab, st.form("login_form"):
            email = st.text_input("Email address", key="login_email", autocomplete="username")
            password = st.text_input("Password", type="password", key="login_pass", autocomplete="current-password")
            if st.form_submit_button("Log in", type="primary", width="stretch"):
                handle_login(email, password)
        with signup_tab, st.form("signup_form"):
            email = st.text_input("Email address", key="reg_email", autocomplete="email")
            password = st.text_input("Password (at least 8 characters)", type="password", key="reg_pass",
                                     autocomplete="new-password")  # fmt: skip
            confirm = st.text_input("Repeat the password", type="password", key="reg_confirm",
                                    autocomplete="new-password")  # fmt: skip
            if st.form_submit_button("Create account", type="primary", width="stretch"):
                if password != confirm:
                    st.error("The passwords do not match.")
                else:
                    ok, message = register_user(email, password)
                    (st.success if ok else st.error)(message)


def handle_login(email: str, password: str) -> None:
    state = st.session_state["login_throttle"]
    email_key = hash_user(email) if email.strip() else ""
    wait = throttle.seconds_left(state, email_key, time.time())
    if wait:
        st.error(f"Too many failed attempts. Wait {wait} seconds, then try again.")
        return
    ok, message = login_user(email, password)
    if ok:
        throttle.record_success(state, email_key)
        st.session_state.update(logged_in=True, user_email=email.strip().lower())
        st.rerun()
    if message == LOGIN_ERROR:
        throttle.record_failure(state, email_key, time.time())
        wait = throttle.seconds_left(state, email_key, time.time())
        if wait:
            message = f"{LOGIN_ERROR} Too many failed attempts. Wait {wait} seconds, then try again."
    st.error(message)


def show_top_bar() -> None:
    with st.container(key="top-bar", horizontal=True, horizontal_alignment="distribute", vertical_alignment="center"):
        st.html("<p class='rc-title'>Recommal</p>")
        st.button("Log out", key="logout", on_click=log_out)


def show_recent() -> None:
    recent = st.session_state["recent"]
    if not recent:
        return
    st.html("<p class='rc-muted'>Recent titles in this session</p>")
    with st.container(key="recent-list", horizontal=True):
        for domain, item_id, title in recent:
            label = f"{components.md_escape(title)} ({components.domain_label(domain)})"
            st.button(label, key=f"recent-{domain}-{item_id}", on_click=open_title, args=(domain, item_id, "recent"))


def show_search_view() -> None:
    st.header("Find recommendations")
    st.write("Choose a starting title. You get titles from the other type: games for an anime, anime for a game.")
    st.session_state["domain_picker"] = st.session_state["last_domain"]
    st.segmented_control("Type of starting title", options=list(DOMAINS), format_func=components.domain_label,
                         key="domain_picker", required=True, on_change=on_domain_change)  # fmt: skip
    domain: str = st.session_state["last_domain"]
    label = components.domain_label(domain).lower()
    st.session_state["query_input"] = st.session_state["last_query"]
    st.text_input(f"{components.domain_label(domain)} title", key="query_input", type="search",
                  placeholder=components.SEARCH_EXAMPLE[domain], autocomplete="off",
                  on_change=on_query_change)  # fmt: skip
    query = st.session_state["last_query"].strip()[:MAX_QUERY_CHARS]
    if len(query) < 2:
        if query:
            st.caption("Type at least 2 characters, then press Enter.")
        else:
            # The style sheet shows one hint: "hint-empty" for an empty field, "hint-typed" once it holds text.
            with st.container(key="hint-empty"):
                st.caption("Type a title, then press Enter to search.")
            with st.container(key="hint-typed"):
                st.caption("Press Enter to search.")
        show_recent()
        return
    try:
        with st.spinner(f"Searching {label} titles..."):
            matches = data.search_titles(domain, query)
    except DB_FAILURES as exc:
        log_failure("Title search", exc)
        st.error(DB_ERROR)
        return
    if not matches:
        st.info(f'No {label} title matches "{components.md_escape(query)}". Check the spelling or try another name.')
        show_recent()
        return
    count = "1 match" if len(matches) == 1 else f"{len(matches)} matches"
    st.caption(f"{count}. Select a title to see its recommendations.")
    with st.container(key="match-list"):
        for match in matches:
            st.button(components.match_label(match), key=f"pick-{domain}-{match['id']}", width="stretch",
                      on_click=open_title, args=(domain, int(match["id"]), "search", query))  # fmt: skip
    show_recent()


def show_results_view(domain: str, item_id: int) -> None:
    user = st.session_state["user_email"]
    variant = assign_variant(user)
    st.button("Back to search", key="back", on_click=back_to_search, args=(domain,))
    try:
        with st.spinner("Loading recommendations..."):
            result = data.results(domain, item_id, variant)
    except DB_FAILURES as exc:
        log_failure("Results lookup", exc)
        st.error(DB_ERROR)
        return
    if not result:
        st.warning("This title is not in the catalogue. Go back and search again.")
        return
    item, recs, rec_domain = result["input_item"], result["recommendations"], result["rec_domain"]
    components.show_breadcrumb(domain, str(item["title"]))
    remember_recent(domain, item_id, str(item["title"]))
    components.show_input_item(item, domain)
    st.divider()
    st.subheader(f"{components.DOMAIN_PLURAL[rec_domain]} similar to {components.md_escape(item['title'])}")
    if not recs:
        st.info("No recommendations exist for this title yet. Go back and choose another title.")
        return

    exposure_key = (domain, item_id, variant)
    if exposure_key not in st.session_state["logged_exposures"]:
        st.session_state["logged_exposures"].add(exposure_key)
        log_event(user, "exposure", query=st.session_state["last_query"] or None, source_domain=domain,
                  source_id=item_id, rec_ids=[int(r["id"]) for r in recs],
                  metadata={"model_ranks": [int(r["rank"]) for r in recs]})  # fmt: skip

    def on_feedback(target_id: int, widget_key: str) -> None:
        # on_change fires only when the user changes the widget, not on every rerun.
        choice = st.session_state.get(widget_key)
        if choice is None:
            return
        relevance = 1 if choice == 1 else -1
        dedupe_key = (domain, item_id, target_id, relevance)
        if dedupe_key in st.session_state["logged_feedback"]:
            return
        st.session_state["logged_feedback"].add(dedupe_key)
        log_event(user, "feedback", source_domain=domain, source_id=item_id, target_id=target_id,
                  relevance=relevance)  # fmt: skip
        st.toast("Feedback saved.")

    def on_open(target_domain: str, target_id: int) -> None:
        open_title(target_domain, target_id, "recommendation", from_domain=domain, from_id=item_id)

    explained = variant == "explained"
    source_themes = item.get("themes") or []
    with st.container(key="rec-grid", horizontal=True, gap="small"):
        for position, rec in enumerate(recs, start=1):
            components.show_recommendation_card(rec, rec_domain, source_themes, explained,
                                                feedback_key=f"fb-{domain}-{item_id}-{rec['id']}",
                                                on_feedback=on_feedback, on_open=on_open,
                                                position=position)  # fmt: skip


# ---- Router. The URL decides the view; session state keeps the user and the search text.
route = routing.read(st.query_params)
if route.domain is not None:
    st.session_state["last_domain"] = route.domain

if not st.session_state["logged_in"]:
    show_login_page()
else:
    show_top_bar()
    if route.invalid:
        st.warning("This link is not valid. Search for a title instead.")
    if route.item_id is None or route.domain is None:
        show_search_view()
    else:
        show_results_view(route.domain, route.item_id)

st.divider()
components.show_about()

if st.session_state["scroll_to_top"]:
    st.session_state["scroll_to_top"] = False
    components.scroll_to_top(key=f"scroll-top-{time.time_ns()}")
