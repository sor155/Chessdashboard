import streamlit as st
import gspread
from google.oauth2.service_account import Credentials
import pandas as pd
import sqlite3
import os

# --- CONFIGURATION ---
# This should be the same URL you used in your old scripts.
SHEET_URL = "https://docs.google.com/spreadsheets/d/1YG4z_MEnhpznrf0dtY8FFK_GNXYMYLrfANDigALO0C0/edit#gid=0"
# This script assumes you have your Google credentials JSON file in the same directory.
# This is the file you used for your GitHub Action and previous scripts.
CREDENTIALS_FILE_PATH = "credentials.json"
# The name of your local SQLite database file.
DB_NAME = "chess_ratings.db"
# The name of the worksheet to import from.
WORKSHEET_NAME = "Rating History"

# Scopes needed to read Google Sheets data.
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.file",
]

def import_history():
    """
    Performs a one-time import of historical rating data from a Google Sheet
    into a local SQLite database.
    """
    print("--- Starting Historical Data Import ---")

    # --- Step 1: Authenticate and Fetch Data from Google Sheets ---
    try:
        if not os.path.exists(CREDENTIALS_FILE_PATH):
            print(f"FATAL ERROR: Credentials file not found at '{CREDENTIALS_FILE_PATH}'")
            print("Please make sure your Google Service Account JSON key file is in the same directory as this script.")
            return

        print(f"Authenticating with Google using '{CREDENTIALS_FILE_PATH}'...")
        creds = Credentials.from_service_account_file(CREDENTIALS_FILE_PATH, scopes=SCOPES)
        client = gspread.authorize(creds)
        
        print(f"Opening Google Sheet: {SHEET_URL}")
        spreadsheet = client.open_by_url(SHEET_URL)
        worksheet = spreadsheet.worksheet(WORKSHEET_NAME)
        
        print(f"Fetching all records from the '{WORKSHEET_NAME}' tab...")
        data = worksheet.get_all_records()
        
        if not data:
            print("No data found in the worksheet. Exiting.")
            return
            
        # Convert the data into a pandas DataFrame for easy handling
        df = pd.DataFrame(data)
        print(f"Successfully fetched {len(df)} rows from Google Sheets.")

    except Exception as e:
        print(f"An error occurred while accessing Google Sheets: {e}")
        return

    # --- Step 2: Prepare Data for SQLite ---
    # The column names in SQLite are slightly different from the Google Sheet headers.
    # We need to rename the DataFrame columns to match the database table schema.
    column_mapping = {
        "Date": "timestamp",
        "Player Name": "player_name",
        "Category": "category",
        "Rating": "rating"
    }
    df.rename(columns=column_mapping, inplace=True)

    # Ensure the columns are in the correct order for the database.
    df = df[['timestamp', 'player_name', 'category', 'rating']]
    
    # --- Step 3: Connect and Write to SQLite Database ---
    try:
        print(f"Connecting to SQLite database: '{DB_NAME}'...")
        with sqlite3.connect(DB_NAME) as conn:
            c = conn.cursor()
            
            # To prevent duplicating data if you run this script more than once,
            # we will delete all existing records from the history table first.
            print("Clearing existing data from 'rating_history' table...")
            c.execute("DELETE FROM rating_history;")
            
            print(f"Writing {len(df)} new records to the 'rating_history' table...")
            # Use pandas' to_sql function for an efficient bulk insert.
            df.to_sql('rating_history', conn, if_exists='append', index=False)
            
            print("Verifying write operation...")
            rows_in_db = c.execute("SELECT COUNT(*) FROM rating_history;").fetchone()[0]
            print(f"Verification successful: Found {rows_in_db} rows in the database.")

    except Exception as e:
        print(f"An error occurred while writing to the SQLite database: {e}")
        return

    print("\n✅ Historical data import completed successfully!")


if __name__ == "__main__":
    import_history()
