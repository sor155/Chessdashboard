Chess Rating and Analysis Dashboard
This project is a web application built with Streamlit to track and visualize the chess ratings of a group of friends, analyze their playing statistics, and perform in-depth, move-by-move analysis of their games.

The application fetches data from the Chess.com API, stores it in a Google Sheet, and presents it through an interactive web interface deployed on Streamlit Community Cloud. The data is kept up-to-date automatically using a scheduled GitHub Action.

Features
Automated Rating Tracker
The backend of the application is a Python script that runs automatically on a schedule via GitHub Actions.

Automatic Data Fetching: Fetches current Rapid, Blitz, and Bullet ratings for a predefined list of players from the Chess.com API.
Persistent Storage: Stores the fetched data in a Google Sheet, creating a historical record of rating changes over time.
Rating Change Calculation: Calculates the total rating change for each player and category since their first recorded rating.
Failure Notifications: Sends an email notification via Gmail if the update script encounters an error, ensuring the owner is aware of any issues.
Web Application Interface
The frontend is an interactive web app built with Streamlit, divided into three main tabs:

1. Dashboard Tab
Current Ratings View: Displays a clean, up-to-date table of the latest ratings and Win/Loss/Draw records for all friends across all categories.
Rating Progression Chart: Features a dynamic line chart that visualizes the rating history of the players.
Interactive Filters: Allows users to filter the progression chart by player, time control category, and a specific date range.
2. Player Stats Tab
Individual Player Analysis: Select a player from a dropdown to see a page dedicated to their stats.
Win Rate by Color: Analyzes a player's game archives to calculate and display their win rates when playing as White and as Black.
Average Accuracy: Shows the player's average game accuracy for both colors.
Opening Repertoire: Identifies and displays the top 5 most frequently played openings for the selected player, separated for White and Black pieces, using the Lichess Community Openings dataset.
3. Game Analysis Tab
PGN Analysis: Allows any user to paste the PGN (Portable Game Notation) of a chess game for a full, move-by-move analysis.
Local Engine Power: Utilizes a local Stockfish chess engine for robust and reliable on-the-fly analysis, ensuring results are always available.
Interactive Board: Displays an interactive chessboard that allows stepping through the game move by move.
Evaluation Bar: Shows a real-time evaluation bar that graphically represents the advantage in the current position.
Move Categorization: Each move is categorized as Excellent, Good, Inaccuracy, Mistake, or Blunder, with a comment explaining the engine's reasoning.
Exportable Data: The full analysis, including evaluations and comments for every move, is displayed in a table and can be downloaded as a CSV file.
Setup and Installation
To run this project locally, follow these steps:

Clone the repository:

Bash

git clone https://github.com/your-username/your-repository-name.git
cd your-repository-name
Install Python dependencies:

Bash

pip install -r requirements.txt
Install Stockfish:
Download the Stockfish engine from stockfishchess.org and ensure the executable is in your system's PATH.

Set up credentials:

Enable the Google Sheets API and Google Drive API in your Google Cloud Platform console.
Create a service account and download its JSON key.
Create a .streamlit directory in the project root.
Place the JSON key information into a file named .streamlit/secrets.toml using the format found in the original project file.
Share your Google Sheet with the client_email from the credentials file, giving it "Editor" permissions.
Run the application:
Use the launcher.py script to start both the background tracker and the Streamlit app simultaneously.

Bash

python launcher.py
Technologies Used
Frontend: Streamlit
Data Storage: Google Sheets
Backend Automation: Python, GitHub Actions
Chess Engine: Stockfish
Key Python Libraries: pandas, altair, requests, gspread, python-chess, stockfish