import sqlite3

def setup_database():
    """Sets up the SQLite database and creates the necessary tables."""
    conn = sqlite3.connect('chess_ratings.db')
    c = conn.cursor()

    # Create table for current ratings
    c.execute('''
        CREATE TABLE IF NOT EXISTS current_ratings (
            friend_name TEXT PRIMARY KEY,
            rapid_rating INTEGER,
            rapid_wld TEXT,
            rapid_change INTEGER,
            blitz_rating INTEGER,
            blitz_wld TEXT,
            blitz_change INTEGER,
            bullet_rating INTEGER,
            bullet_wld TEXT,
            bullet_change INTEGER
        )
    ''')

    # Create table for rating history
    c.execute('''
        CREATE TABLE IF NOT EXISTS rating_history (
            timestamp TEXT,
            player_name TEXT,
            category TEXT,
            rating INTEGER
        )
    ''')

    conn.commit()
    conn.close()
    print("Database `chess_ratings.db` and tables created successfully.")

if __name__ == '__main__':
    setup_database()