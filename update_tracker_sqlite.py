import sqlite3
import requests
from datetime import datetime
import pandas as pd
import sys

# --- CONFIGURATION ---
DB_NAME = "chess_ratings.db"
friends = [
    ("Ulysse", "RealUlysse", ""),
    ("Simon", "Poulet_tao", ""),
    ("Adrien", "adrienbourque", ""),
    ("Alex", "naatiry", ""),
    ("Kevin", "Kevor24", ""),
]

def get_api_data(username):
    """Fetches player stats from the Chess.com API."""
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
    """Calculates the difference between two ratings."""
    if isinstance(new, int) and isinstance(old, int):
        return new - old
    return None

def safe_wld(stats):
    """Safely formats the Win/Loss/Draw string."""
    try:
        w = int(stats.get("win", 0) or 0)
        l = int(stats.get("loss", 0) or 0)
        d = int(stats.get("draw", 0) or 0)
        return f"{w}/{l}/{d}"
    except:
        return "0/0/0"

def safe_int(val):
    """Safely converts a value to an integer."""
    try:
        return int(val)
    except (ValueError, TypeError):
        return None

def get_stats_from_data(data, category):
    """Extracts rating and W/L/D stats for a specific category."""
    stats = {"rating": None, "win": 0, "loss": 0, "draw": 0}
    category_data = data.get(f"chess_{category}", {}) if data else {}

    if category_data:
        stats["rating"] = category_data.get("last", {}).get("rating")
        record = category_data.get("record", {}) or {}
        stats["win"] = record.get("win", 0) or 0
        stats["loss"] = record.get("loss", 0) or 0
        stats["draw"] = record.get("draw", 0) or 0

    return stats

def get_first_rating(conn, player, cat):
    """Gets the earliest recorded rating for a player in a specific category."""
    c = conn.cursor()
    c.execute("""
        SELECT rating FROM rating_history
        WHERE player_name = ? AND category = ?
        ORDER BY timestamp ASC LIMIT 1
    """, (player, cat))
    result = c.fetchone()
    return result[0] if result else None

def run_update():
    """The main function to run a single update and write to the SQLite database."""
    try:
        conn = sqlite3.connect(DB_NAME)
        c = conn.cursor()
    except sqlite3.Error as e:
        print(f"FATAL: Could not connect to database {DB_NAME}. Error: {e}")
        sys.exit(1)

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

        first_rapid = get_first_rating(conn, name, 'C - Rapid')
        first_blitz = get_first_rating(conn, name, 'C - Blitz')
        first_bullet = get_first_rating(conn, name, 'C - Bullet')

        current_row_data = (
            name,
            rapid_rating, safe_wld(rapid), calculate_diff(rapid_rating, first_rapid),
            blitz_rating, safe_wld(blitz), calculate_diff(blitz_rating, first_blitz),
            bullet_rating, safe_wld(bullet), calculate_diff(bullet_rating, first_bullet),
        )

        c.execute('''
            INSERT OR REPLACE INTO current_ratings (
                friend_name, rapid_rating, rapid_wld, rapid_change,
                blitz_rating, blitz_wld, blitz_change,
                bullet_rating, bullet_wld, bullet_change
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', current_row_data)

        if rapid_rating is not None:
            history_rows_to_append.append((timestamp, name, "C - Rapid", rapid_rating))
        if blitz_rating is not None:
            history_rows_to_append.append((timestamp, name, "C - Blitz", blitz_rating))
        if bullet_rating is not None:
            history_rows_to_append.append((timestamp, name, "C - Bullet", bullet_rating))

    if history_rows_to_append:
        print("Writing new data to 'rating_history' table...")
        c.executemany('INSERT INTO rating_history VALUES (?,?,?,?)', history_rows_to_append)

    conn.commit()
    conn.close()
    print("\n✅ SQLite database update complete!")

if __name__ == "__main__":
    print(f"\n--- Running update at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ---")
    run_update()
    print(f"\n--- Update complete. ---")