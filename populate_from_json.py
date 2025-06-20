import json
import sqlite3

def populate_db():
    conn = sqlite3.connect('chess_ratings.db')
    c = conn.cursor()

    with open('data.json') as f:
        data = json.load(f)

    for item in data:
        c.execute('''
            INSERT OR REPLACE INTO current_ratings (friend_name, rapid_rating, blitz_rating, bullet_rating)
            VALUES (?, ?, ?, ?)
        ''', (item["Friend's Name"], item["C - Rapid"], item["C - Blitz"], item["C - Bullet"]))

    conn.commit()
    conn.close()
    print("Database populated from data.json")

if __name__ == '__main__':
    populate_db()