import gspread
from google.oauth2.service_account import Credentials
import requests
from datetime import datetime
import pandas as pd
import smtplib
import ssl
import os
import json
import sys

# --- CONFIGURATION ---
SHEET_URL = "https://docs.google.com/spreadsheets/d/1YG4z_MEnhpznrf0dtY8FFK_GNXYMYLrfANDigALO0C0/edit?gid=1213756490#gid=1213756490"
SCOPES = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive.file']

# ... (rest of configuration is the same)
ENABLE_EMAIL_NOTIFICATIONS = True
SENDER_EMAIL = "thesor155@gmail.com"
RECEIVER_EMAIL = "thesor155@gmail.com"
SENDER_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD")
manual_starting_ratings = {
    "Simon": {"C - Blitz": 412, "C - Rapid": 1006, "C - Bullet": 716},
    "Ulysse": {"C - Blitz": 1491, "C - Rapid": 1971, "C - Bullet": 1349},
    "Alex": {"C - Blitz": 268, "C - Rapid": 841, "C - Bullet": 487},
    "Adrien": {"C - Rapid": 1619, "C - Bullet": 747, "C - Blitz": 1163},
    "Kevin": {"C - Bullet": 577, "C - Rapid": 702, "C - Blitz": 846}
}
friends = [
    ("Ulysse", "RealUlysse", ""),
    ("Simon", "Poulet_tao", ""),
    ("Adrien", "adrienbourque", ""),
    ("Alex", "naatiry", ""),
    ("Kevin", "Kevor24", ""),
]


def send_failure_email(error_message):
    if not ENABLE_EMAIL_NOTIFICATIONS or not SENDER_APP_PASSWORD:
        print("Email notifications disabled or password not set.")
        return
    smtp_server, port = "smtp.gmail.com", 465
    subject = "Chess Tracker Script FAILED"
    body = f"The chess rating tracker script failed to complete.\n\nError details:\n{error_message}"
    message = f"Subject: {subject}\n\n{body}"
    context = ssl.create_default_context()
    try:
        with smtplib.SMTP_SSL(smtp_server, port, context=context) as server:
            server.login(SENDER_EMAIL, SENDER_APP_PASSWORD)
            server.sendmail(SENDER_EMAIL, RECEIVER_EMAIL, message)
    except Exception as e:
        print(f"Could not send failure email. Error: {e}")


def get_credentials():
    """Authenticates with Google using credentials from an environment variable."""
    try:
        gcp_sa_key_str = os.environ.get("GCP_SA_KEY")
        if not gcp_sa_key_str:
            print("FATAL: GCP_SA_KEY environment variable not found.")
            sys.exit(1)

        # Parse the JSON string from the environment variable into a dictionary
        creds_dict = json.loads(gcp_sa_key_str)

        # Authenticate using the dictionary
        creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
        client = gspread.authorize(creds)

        print("✅ Successfully authenticated with Google.")
        return client

    except json.JSONDecodeError:
        print("FATAL: Could not parse GCP_SA_KEY. Ensure it's valid JSON and does not contain any extra text or TOML headers.")
        sys.exit(1)
    except Exception as e:
        print(f"FATAL: An unexpected authentication error occurred: {e}")
        sys.exit(1)

def get_api_data(username):
    if not username:
        return None
    url = f"https://api.chess.com/pub/player/{username}/stats"
    try:
        response = requests.get(url, headers={"User-Agent": "PythonChessTracker/1.0"})
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        print(f"  ERROR (Chess.com for '{username}'): {e}")
        return None

def calculate_diff(new, old):
    if isinstance(new, int) and isinstance(old, int):
        return f"'{new - old}"
    return "'N/A"

def safe_wld(stats):
    try:
        w = int(stats.get("win", 0) or 0)
        l = int(stats.get("loss", 0) or 0)
        d = int(stats.get("draw", 0) or 0)
        return f"'{w}/{l}/{d}"
    except:
        return "'0/0/0"

def safe_int(val):
    try:
        return int(val)
    except:
        return None

def get_stats_from_data(data, category):
    stats = {"rating": None, "win": 0, "loss": 0, "draw": 0}
    category_data = data.get(f"chess_{category}", {}) if data else {}

    if category_data:
        stats["rating"] = category_data.get("last", {}).get("rating")
        record = category_data.get("record", {}) or {}
        stats["win"] = record.get("win", 0) or 0
        stats["loss"] = record.get("loss", 0) or 0
        stats["draw"] = record.get("draw", 0) or 0

    return stats


def run_update():
    """The main function to run a single update."""
    client = get_credentials()
    if not client:
        print("FATAL: Could not get Google API client. Exiting.")
        sys.exit(1)
    
    try:
        print(f"Attempting to open spreadsheet...")
        spreadsheet = client.open_by_url(SHEET_URL)
        print("✅ Successfully opened spreadsheet.")
        
        worksheet_current = spreadsheet.worksheet('Current Ratings')
        worksheet_history = spreadsheet.worksheet('Rating History')
        history_data = worksheet_history.get_all_records()
        history_df = pd.DataFrame(history_data) if history_data else pd.DataFrame(columns=['Date', 'Player Name', 'Category', 'Rating'])
        if not history_df.empty:
            history_df['Date'] = pd.to_datetime(history_df['Date'])
            history_df['Rating'] = pd.to_numeric(history_df['Rating'], errors='coerce')

        def get_first_rating(player, cat):
            if player in manual_starting_ratings and cat in manual_starting_ratings[player]:
                return manual_starting_ratings[player][cat]
            player_history = history_df[(history_df['Player Name'] == player) & (history_df['Category'] == cat)]
            if player_history.empty:
                return None
            return player_history.sort_values(by='Date').iloc[0]['Rating']

        current_ratings_data = []
        history_rows_to_append = []
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        for name, chesscom_user, _ in friends:
            print(f"Fetching ratings for {name}...")
            api_data = get_api_data(chesscom_user)
            rapid = get_stats_from_data(api_data, "rapid")
            blitz = get_stats_from_data(api_data, "blitz")
            bullet = get_stats_from_data(api_data, "bullet")
            rapid_rating = safe_int(rapid['rating'])
            blitz_rating = safe_int(blitz['rating'])
            bullet_rating = safe_int(bullet['rating'])
            first_rapid = safe_int(get_first_rating(name, 'C - Rapid'))
            first_blitz = safe_int(get_first_rating(name, 'C - Blitz'))
            first_bullet = safe_int(get_first_rating(name, 'C - Bullet'))
            current_row = [
                name,
                rapid_rating if rapid_rating is not None else "N/A", safe_wld(rapid), calculate_diff(rapid_rating, first_rapid),
                blitz_rating if blitz_rating is not None else "N/A", safe_wld(blitz), calculate_diff(blitz_rating, first_blitz),
                bullet_rating if bullet_rating is not None else "N/A", safe_wld(bullet), calculate_diff(bullet_rating, first_bullet)
            ]
            current_ratings_data.append(current_row)
            if isinstance(rapid_rating, int):
                history_rows_to_append.append([timestamp, name, "C - Rapid", rapid_rating])
            if isinstance(blitz_rating, int):
                history_rows_to_append.append([timestamp, name, "C - Blitz", blitz_rating])
            if isinstance(bullet_rating, int):
                history_rows_to_append.append([timestamp, name, "C - Bullet", bullet_rating])

        header_current = [
            "Friend's Name", "Rapid", "W/L/D Rapid", "Rapid Change",
            "Blitz", "W/L/D Blitz", "Blitz Change",
            "Bullet", "W/L/D Bullet", "Bullet Change"
        ]
        
        print("Updating 'Current Ratings' sheet...")
        worksheet_current.clear()
        worksheet_current.update('A1', [header_current] + current_ratings_data, value_input_option='USER_ENTERED')

        if history_rows_to_append:
            print("Updating 'Rating History' sheet...")
            worksheet_history.append_rows(history_rows_to_append, value_input_option='USER_ENTERED')

        print("\n✅✅✅ Sheet updates complete!")

    except Exception as e:
        print(f"FATAL: An error occurred during the sheet update process: {e}")
        send_failure_email(e)
        sys.exit(1)


if __name__ == "__main__":
    print(f"--- Running update at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ---")
    run_update()
    print(f"--- Update process finished. ---")