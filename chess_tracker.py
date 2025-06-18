import requests
import pandas as pd
from datetime import datetime

# --- List of your friends ---
# Add your friends' information in the following format:
# ("Display Name", "Chess.com Username", "Lichess Username")
# If a friend doesn't have an account on a site, use an empty string "".
friends = [
    ("Ulysse", "RealUlysse", ""),
    ("Simon", "Poulet_tao", ""),
    ("Adrien", "adrienbourque", ""),
    ("Alex", "naatiry", ""),
    ("Kevin", "Kevor24", ""), # Example with famous players
]

def get_chesscom_ratings(username):
    """Fetches ratings for a user from the Chess.com API."""
    if not username:
        return {"Rapid": "N/A", "Blitz": "N/A", "Bullet": "N/A"}

    try:
        url = f"https://api.chess.com/pub/player/{username}/stats"
        response = requests.get(url, headers={"User-Agent": "MyChessTracker/1.0"})
        response.raise_for_status()  # Will raise an HTTPError for bad responses (4xx or 5xx)
        data = response.json()

        return {
            "Rapid": data.get("chess_rapid", {}).get("last", {}).get("rating", "N/A"),
            "Blitz": data.get("chess_blitz", {}).get("last", {}).get("rating", "N/A"),
            "Bullet": data.get("chess_bullet", {}).get("last", {}).get("rating", "N/A"),
        }
    except requests.exceptions.RequestException as e:
        print(f"Error fetching Chess.com data for {username}: {e}")
        return {"Rapid": "Error", "Blitz": "Error", "Bullet": "Error"}

def get_lichess_ratings(username):
    """Fetches ratings for a user from the Lichess.org API."""
    if not username:
        return {"Rapid": "N/A", "Blitz": "N/A", "Bullet": "N/A"}

    try:
        url = f"https://lichess.org/api/user/{username}"
        response = requests.get(url, headers={"User-Agent": "MyChessTracker/1.0"})
        response.raise_for_status()
        data = response.json()

        return {
            "Rapid": data.get("perfs", {}).get("rapid", {}).get("rating", "N/A"),
            "Blitz": data.get("perfs", {}).get("blitz", {}).get("rating", "N/A"),
            "Bullet": data.get("perfs", {}).get("bullet", {}).get("rating", "N/A"),
        }
    except requests.exceptions.RequestException as e:
        print(f"Error fetching Lichess data for {username}: {e}")
        return {"Rapid": "Error", "Blitz": "Error", "Bullet": "Error"}

def main():
    """Main function to run the tracker."""
    all_ratings_data = []

    for name, chesscom_user, lichess_user in friends:
        print(f"Fetching ratings for {name}...")
        chesscom_ratings = get_chesscom_ratings(chesscom_user)
        lichess_ratings = get_lichess_ratings(lichess_user)

        player_data = {
            "Friend's Name": name,
            "C - Rapid": chesscom_ratings["Rapid"],
            "C - Blitz": chesscom_ratings["Blitz"],
            "C - Bullet": chesscom_ratings["Bullet"],
            "L - Rapid": lichess_ratings["Rapid"],
            "L - Blitz": lichess_ratings["Blitz"],
            "L - Bullet": lichess_ratings["Bullet"],
        }
        all_ratings_data.append(player_data)

    # Create a pandas DataFrame for better display and export
    df = pd.DataFrame(all_ratings_data)
    df = df.set_index("Friend's Name")

    # --- Display the results in the terminal ---
    print("\n--- Chess Rating Tracker ---")
    print(df.to_string())
    print("----------------------------")

    # --- Save the results to a CSV file ---
    timestamp = datetime.now().strftime("%Y-%m-%d")
    filename = f"chess_ratings_{timestamp}.csv"
    df.to_csv(filename)
    print(f"\nRatings saved to {filename}")

if __name__ == "__main__":
    main()