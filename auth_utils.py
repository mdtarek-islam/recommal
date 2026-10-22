import psycopg2
import os
from dotenv import load_dotenv
import bcrypt
import streamlit as st
from bs4 import BeautifulSoup
import html

# Load .env variables
load_dotenv()
user = os.getenv("user")
password = os.getenv("password")
host = os.getenv("host")
port = os.getenv("port")
dbname = os.getenv("dbname") # Add your dbname to .env as well

# --- Database Connection ---

def get_db_connection():
    """Establishes a connection to the PostgreSQL database."""
    try:
        conn = psycopg2.connect(
            dbname=dbname,
            user=user,
            password=password,
            host=host,
            port=port
        )
        return conn
    except Exception as e:
        st.error(f"Error connecting to database: {e}")
        return None
    
def clean_synopsis(html_text):
    """
    Cleans HTML text from a synopsis string.
    Removes tags (like images, divs) and unescapes HTML entities.
    """
    if not html_text:
        return "No synopsis available."
    
    try:
        # 1. Parse the HTML
        soup = BeautifulSoup(html_text, "html.parser")
        
        # 2. Remove unwanted tags that don't contain text (like images, scripts, styles)
        for tag in soup(["img", "div", "script", "style"]):
            tag.decompose() # Remove the tag and all its contents
        
        # 3. Get the text, separating paragraphs with newlines
        text = soup.get_text(separator="\n")
        
        # 4. Unescape HTML entities (e.g., &amp; -> &)
        text = html.unescape(text)
        
        # 5. Clean up excessive whitespace and multiple newlines
        lines = [line.strip() for line in text.splitlines()]
        cleaned_lines = [line for line in lines if line] # Filter out empty lines
        
        return "\n".join(cleaned_lines)
        
    except Exception as e:
        print(f"Error cleaning synopsis: {e}")
        return html_text # Return original text if cleaning fails

# --- Password Hashing & Verification (This is the "strong encryption") ---

def hash_password(password):
    """Hashes a plaintext password using bcrypt."""
    salt = bcrypt.gensalt()
    hashed_pw = bcrypt.hashpw(password.encode('utf-8'), salt)
    return hashed_pw.decode('utf-8') # Store as a string in the DB

def check_password(hashed_password, user_password):
    """Checks if the provided password matches the stored hash."""
    return bcrypt.checkpw(user_password.encode('utf-8'), hashed_password.encode('utf-8'))

# --- User Management Functions ---

def register_user(email, password):
    """Registers a new user by hashing their password and saving to DB."""
    if not email or not password:
        return False, "Email and password are required."
        
    hashed_pw = hash_password(password)
    conn = get_db_connection()
    if conn:
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO users (email, password_hash) VALUES (%s, %s)",
                    (email, hashed_pw)
                )
                conn.commit()
            return True, "Registration successful! Please log in."
        except psycopg2.IntegrityError:
            return False, "Email already exists."
        except Exception as e:
            return False, f"An error occurred: {e}"
        finally:
            conn.close()
    return False, "Database connection failed."

def login_user(email, password):
    """Logs in a user by verifying their email and password hash."""
    if not email or not password:
        return False, "Please enter email and password."

    conn = get_db_connection()
    if conn:
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT email, password_hash FROM users WHERE email = %s", (email,))
                user = cur.fetchone()
                
                if user:
                    stored_email, stored_hash = user
                    # Verify password
                    if check_password(stored_hash, password):
                        return True, "Login successful!"
                    else:
                        return False, "Incorrect email or password."
                else:
                    return False, "Incorrect email or password."
        except Exception as e:
            return False, f"An error occurred: {e}"
        finally:
            conn.close()
            
    return False, "Database connection failed."

# (Keep all your existing auth functions: get_db_connection, hash_password, etc.)
# --- Add the two new functions below ---

def get_media_details(media_id, media_domain, cursor):
    """
    Fetches the synopsis and image URL for a given item from its domain table.
    This function re-uses the provided database cursor for efficiency.
    """
    synopsis, image_url = "No synopsis available.", "default_image_url.png" # Fallbacks

    try:
        if media_domain == 'anime':
            # Get anime synopsis
            cursor.execute("SELECT synopsis FROM animes WHERE id = %s", (media_id,))
            synopsis_result = cursor.fetchone()
            if synopsis_result:
                raw_synopsis = synopsis_result[0]
                synopsis = clean_synopsis(raw_synopsis) # Clean the text

            # Get anime picture
            cursor.execute("SELECT large_url FROM anime_main_pictures WHERE anime_id = %s", (media_id,))
            image_result = cursor.fetchone()
            if image_result:
                image_url = image_result[0]
            
            return synopsis, image_url

        elif media_domain == 'game':
            # This large UNION query searches all 10 game tables at once.
            union_query = """
                SELECT detailed_description, header_image FROM (
                    SELECT id, detailed_description, header_image FROM steam_games_chunk_1 WHERE id = %s
                    UNION ALL
                    SELECT id, detailed_description, header_image FROM steam_games_chunk_2 WHERE id = %s
                    UNION ALL
                    SELECT id, detailed_description, header_image FROM steam_games_chunk_3 WHERE id = %s
                    UNION ALL
                    SELECT id, detailed_description, header_image FROM steam_games_chunk_4 WHERE id = %s
                    UNION ALL
                    SELECT id, detailed_description, header_image FROM steam_games_chunk_5 WHERE id = %s
                    UNION ALL
                    SELECT id, detailed_description, header_image FROM steam_games_chunk_6 WHERE id = %s
                    UNION ALL
                    SELECT id, detailed_description, header_image FROM steam_games_chunk_7 WHERE id = %s
                    UNION ALL
                    SELECT id, detailed_description, header_image FROM steam_games_chunk_8 WHERE id = %s
                    UNION ALL
                    SELECT id, detailed_description, header_image FROM steam_games_chunk_9 WHERE id = %s
                    UNION ALL
                    SELECT id, detailed_description, header_image FROM steam_games_chunk_10 WHERE id = %s
                ) AS all_games
            """
            # We must provide the media_id 10 times, one for each part of the UNION
            params = (media_id,) * 10
            cursor.execute(union_query, params)
            game_details = cursor.fetchone()
            
            if game_details:
                raw_synopsis = game_details[0]
                synopsis = clean_synopsis(raw_synopsis) # Clean the text
                image_url = game_details[1]
                
            return synopsis, image_url

    except Exception as e:
        st.error(f"Error in get_media_details: {e}")
        return synopsis, image_url # Return fallbacks

    return synopsis, image_url


def get_results_data(search_title, search_domain):
    """
    Fetches all data needed for the results page: input item details
    and all 5 recommended item details.
    """
    conn = get_db_connection()
    if not conn:
        st.error("Database connection failed.")
        return None

    try:
        with conn.cursor() as cur:
            # 1. Get the recommendations row
            cur.execute(
                "SELECT * FROM siamese_recommendations WHERE chosen_title ILIKE %s AND chosen_domain = %s LIMIT 1",
                (f"%{search_title}%", search_domain)
            )
            siamese_row = cur.fetchone()

            if not siamese_row:
                st.warning("No recommendations found for that title.")
                return None

            # 2. Unpack Siamese data
            chosen_id = siamese_row[1]
            chosen_title = siamese_row[2] # Get the correctly cased title
            rec_domain = siamese_row[3]

            # 3. Get Input Item Details
            input_synopsis, input_image = get_media_details(chosen_id, search_domain, cur)
            input_data = {
                "title": chosen_title,
                "synopsis": input_synopsis if input_synopsis else "No synopsis found.",
                "image_url": input_image
            }

            # 4. Get Recommended Items Details
            rec_list = []
            for i in range(5):
                rec_id_index = 4 + (i * 3)
                rec_title_index = 5 + (i * 3)
                
                rec_id = siamese_row[rec_id_index]
                rec_title = siamese_row[rec_title_index]
                
                if rec_id and rec_title:
                    rec_synopsis, rec_image = get_media_details(rec_id, rec_domain, cur)
                    rec_list.append({
                        "title": rec_title,
                        "synopsis": rec_synopsis if rec_synopsis else "No synopsis found.",
                        "image_url": rec_image
                    })
            
            return {
                "input_item": input_data,
                "recommendations": rec_list,
                "rec_domain": rec_domain
            }

    except Exception as e:
        st.error(f"Error in get_results_data: {e}")
        return None
    finally:
        conn.close()

