import streamlit as st
from auth_utils import register_user, login_user, get_results_data # Updated import

# --- Page Configuration (must be the first st command) ---
# Set layout to "wide" to match your template
st.set_page_config(page_title="RecommaI", layout="wide")

# --- Initialize Session State ---
# This holds the user's login status and search state.
if 'logged_in' not in st.session_state:
    st.session_state['logged_in'] = False
if 'user_email' not in st.session_state:
    st.session_state['user_email'] = ""
if 'search_query' not in st.session_state:
    st.session_state['search_query'] = None
if 'search_domain' not in st.session_state:
    st.session_state['search_domain'] = None

# ===============================================
# ===         LOGIN PAGE VIEW                 ===
# ===============================================

def show_login_page():
    """Displays the login and registration forms."""
    
    col1, col2, col3 = st.columns([1, 1.5, 1]) 

    with col2:
        with st.container(border=True):
            try:
                st.image("logo.png") 
            except:
                st.error("Logo image not found. Make sure 'logo.png' is in the same folder.")
                
            st.title("Sign in to Unlock Your World")

            tab1, tab2 = st.tabs(["Log In", "Sign Up"])

            # --- LOGIN FORM ---
            with tab1:
                with st.form(key='login_form'):
                    email = st.text_input("Email Address", key="login_email")
                    password = st.text_input("Password", type="password", key="login_pass")
                    login_button = st.form_submit_button(label="Log In", use_container_width=True)
                    
                    if login_button:
                        success, message = login_user(email, password)
                        if success:
                            st.session_state['logged_in'] = True
                            st.session_state['user_email'] = email
                            st.rerun() 
                        else:
                            st.error(message)

            # --- REGISTRATION FORM ---
            with tab2:
                with st.form(key='signup_form'):
                    reg_email = st.text_input("Email Address", key="reg_email")
                    reg_password = st.text_input("Create Password", type="password", key="reg_pass")
                    reg_confirm_pass = st.text_input("Confirm Password", type="password", key="reg_confirm")
                    signup_button = st.form_submit_button(label="Create Account", use_container_width=True)

                    if signup_button:
                        if reg_password == reg_confirm_pass:
                            success, message = register_user(reg_email, reg_password)
                            if success:
                                st.success(message)
                            else:
                                st.error(message)
                        else:
                            st.error("Passwords do not match.")

# ===============================================
# ===         SEARCH VIEW                     ===
# ===============================================

def show_search_view():
    """Displays the main search bar and domain selection."""
    st.title("Find Your Next Obsession")
    st.subheader("Select a domain and enter a title to get started!")

    # Use a form to group the inputs and search button
    with st.form(key="search_form"):
        col1, col2 = st.columns([1, 3])
        with col1:
            # 1. DOMAIN DROPDOWN
            domain = st.selectbox(
                "I have an...",
                ("Game", "Anime"),
                index=0 # Default to "Game"
            )
        with col2:
            # 2. SEARCH BAR
            query = st.text_input(
                "Enter title",
                placeholder="e.g., Elden Ring, One Piece, or Studio Ghibli"
            )
        
        # 3. SUBMIT BUTTON
        submit_button = st.form_submit_button(label="Find Recommendations")

    if submit_button and query:
        # When user searches, save state and rerun to show results view
        st.session_state['search_query'] = query
        st.session_state['search_domain'] = domain.lower() # "game" or "anime"
        st.rerun()
    elif submit_button and not query:
        st.error("Please enter a title to search.")

# ===============================================
# ===         RESULTS VIEW                    ===
# ===============================================

def show_results_view():
    """
    Displays the results page based on the template,
    using data from session state.
    """
    query = st.session_state['search_query']
    domain = st.session_state['search_domain']
    
    # --- "New Search" Button ---
    if st.button("← Start a New Search"):
        # Clear the search state and rerun to go back to search view
        st.session_state['search_query'] = None
        st.session_state['search_domain'] = None
        st.rerun()

    # --- Fetch Data ---
    # This queries the DB and gets all image URLs and synopses
    data = get_results_data(query, domain)
    
    if not data:
        st.error(f"Could not find any recommendations for '{query}'. Please try another title.")
        return # Stop execution if no data

    # --- 1. Display Input Item (Top 60%) ---
    input_item = data['input_item']
    st.header(f"Based on your input: {input_item['title']}")
    
    col1, col2 = st.columns([1, 2]) # Ratio as per your template
    
    with col1:
        st.image(input_item['image_url'], use_container_width=True)
    
    with col2:
        # Create the grey info box from the template
        with st.container(border=True):
            # We don't have Genre/Start Date in the DB, so we'll just show synopsis.
            
            # Synopsis Preview
            synopsis_preview = " ".join(input_item['synopsis'].split()[:40]) + "..."
            st.write(f"**Synopsis:** {synopsis_preview}")
            
            # Full Synopsis in an Expander (the "hover" effect)
            with st.expander("Read full synopsis"):
                st.write(input_item['synopsis'])

    st.divider()

    # --- 2. Display Recommendations (Bottom 40%) ---
    st.header(f"Recommended {data['rec_domain'].capitalize()}s")

    # Use 5 columns for the horizontal list, as per the template
    cols = st.columns(5)
    
    for i, rec in enumerate(data['recommendations']):
        with cols[i]:
            # This container creates the "card" for each recommendation
            with st.container(border=True):
                st.image(rec['image_url'], use_container_width=True)
                st.markdown(f"**{rec['title']}**")
                
                # Synopsis preview
                rec_synopsis_preview = " ".join(rec['synopsis'].split()[:15]) + "..."
                st.write(rec_synopsis_preview)
                
                # Full details in an expander
                # This is the Streamlit-native way to do your "hover to expand" request
                with st.expander("See details"):
                    st.write(rec['synopsis'])

# ===============================================
# ===         MAIN APP ROUTER                 ===
# ===============================================

# --- Top-level Logout Button (appears on all pages when logged in) ---
if st.session_state['logged_in']:
    # Place logout button in the top-right corner
    cols = st.columns([10, 1])
    with cols[1]:
        if st.button("Log Out"):
            st.session_state['logged_in'] = False
            st.session_state['user_email'] = ""
            st.session_state['search_query'] = None
            st.session_state['search_domain'] = None
            st.rerun()

# --- Main Logic: Show Login or App ---
if not st.session_state['logged_in']:
    show_login_page()
else:
    # User is logged in, decide which view to show
    if st.session_state['search_query'] is None:
        show_search_view() # Show search bar
    else:
        show_results_view() # Show results page