import streamlit as st
import gspread
from google.oauth2.service_account import Credentials
import pandas as pd
import altair as alt
import requests
from datetime import datetime, date
from collections import Counter
import io
import chess.pgn
from datasets import load_dataset

# --- PAGE CONFIG ---
st.set_page_config(layout="wide", page_title="Chess Dashboard")

# --- CONFIGURATION ---
SHEET_URL = "https://docs.google.com/spreadsheets/d/1YG4z_MEnhpznrf0dtY8FFK_GNXYMYLrfANDigALO0C0/edit#gid=0"
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.file",
]
FRIENDS = [
    ("Ulysse", "realulysse"),
    ("Simon", "poulet_tao"),
    ("Adrien", "adrienbourque"),
    ("Alex", "naatiry"),
    ("Kevin", "kevor24"),
]
HEADERS = {"User-Agent": "ChessTrackerBot/1.0"}


# --- Load Lichess ECO dataset ---
@st.cache_resource
def load_opening_maps():
    ds = load_dataset("Lichess/chess-openings", split="train")
    eco_map = {row["eco"]: row["name"] for row in ds}
    pgn_map = {row["pgn"]: row["name"] for row in ds}
    return eco_map, pgn_map


eco_map, pgn_map = load_opening_maps()


# --- Chess.com avatar fetch ---
def get_chesscom_avatar(username):
    try:
        r = requests.get(
            f"https://api.chess.com/pub/player/{username}", headers=HEADERS
        )
        r.raise_for_status()
        return r.json().get("avatar", None)
    except:
        return None


# --- Google Sheets Access ---
@st.cache_data(ttl=3600)
def fetch_current_and_history():
    creds = Credentials.from_service_account_file("credentials.json", scopes=SCOPES)
    client = gspread.authorize(creds)
    ss = client.open_by_url(SHEET_URL)
    curr = ss.worksheet("Current Ratings").get_all_records()
    hist = ss.worksheet("Rating History").get_all_records()
    return curr, hist


# --- Chess.com API Helpers ---
def fetch_user_stats(username):
    url = f"https://api.chess.com/pub/player/{username}/stats"
    r = requests.get(url, headers=HEADERS)
    r.raise_for_status()
    return r.json()


def fetch_archives(username):
    url = f"https://api.chess.com/pub/player/{username}/games/archives"
    r = requests.get(url, headers=HEADERS)
    r.raise_for_status()
    return r.json().get("archives", [])


def fetch_games_in_month(url):
    r = requests.get(url, headers=HEADERS)
    r.raise_for_status()
    return r.json().get("games", [])


# --- PGN parsing with fallback to Lichess ECO data ---
def get_opening_from_pgn(pgn_text):
    try:
        game = chess.pgn.read_game(io.StringIO(pgn_text))
        eco = game.headers.get("ECO")
        if eco and eco in eco_map:
            return eco_map[eco]
        board = game.board()
        moves = []
        for move in game.mainline_moves():
            board.push(move)
            moves.append(board.san(move))
        move_seq = " ".join(moves[:10])
        for pgn_prefix, name in pgn_map.items():
            if move_seq.startswith(pgn_prefix):
                return name
        return "N/A"
    except:
        return "N/A"


# --- Player Stats Calculation with Color Split ---
@st.cache_data(ttl=86400, show_spinner=True)
def compute_player_stats(username):
    # Fetch overall stats as provided by Chess.com API.
    stats = fetch_user_stats(username)
    categories = ["rapid", "blitz", "bullet"]
    overall_rates = {}

    for cat in categories:
        rec = stats.get(f"chess_{cat}", {}).get("record", {})
        w, l, d = rec.get("win", 0), rec.get("loss", 0), rec.get("draw", 0)
        total = w + l + d
        overall_rates[cat] = f"{100 * w / total:.1f}%" if total > 0 else "N/A"

    # For color-split stats, use recent archive games.
    archives = fetch_archives(username)[-4:]  # last 4 months
    # Counters for overall openings (if needed) and for white/black separately.
    overall_opening_counts = Counter()

    wins_white = 0
    total_white = 0
    wins_black = 0
    total_black = 0
    white_opening_counts = Counter()
    black_opening_counts = Counter()

    username_lower = username.lower()

    for archive_url in archives:
        try:
            games = fetch_games_in_month(archive_url)
            for g in games:
                # Try to get opening name either directly or via fallback PGN parsing.
                opening_name = g.get("opening", {}).get("name")
                if not opening_name:
                    pgn = g.get("pgn")
                    if pgn:
                        opening_name = get_opening_from_pgn(pgn)
                if opening_name:
                    overall_opening_counts[opening_name] += 1

                # Check which color the player was and update
                if "white" in g and "black" in g:
                    white_info = g["white"]
                    black_info = g["black"]

                    if white_info.get("username", "").lower() == username_lower:
                        total_white += 1
                        # Check white result; we assume a "win" string indicates a win.
                        if white_info.get("result") == "win":
                            wins_white += 1
                        if opening_name:
                            white_opening_counts[opening_name] += 1
                    elif black_info.get("username", "").lower() == username_lower:
                        total_black += 1
                        if black_info.get("result") == "win":
                            wins_black += 1
                        if opening_name:
                            black_opening_counts[opening_name] += 1
        except:
            continue

    winrate_white = (
        f"{100 * wins_white / total_white:.1f}%" if total_white > 0 else "N/A"
    )
    winrate_black = (
        f"{100 * wins_black / total_black:.1f}%" if total_black > 0 else "N/A"
    )
    overall_top_opening = (
        overall_opening_counts.most_common(1)[0][0] if overall_opening_counts else "N/A"
    )
    white_top_opening = (
        white_opening_counts.most_common(1)[0][0] if white_opening_counts else "N/A"
    )
    black_top_opening = (
        black_opening_counts.most_common(1)[0][0] if black_opening_counts else "N/A"
    )
    top_openings_white = white_opening_counts.most_common(5)
    top_openings_black = black_opening_counts.most_common(5)

    # Return all computed stats in a dictionary
    return {
        "overall_rates": overall_rates,
        "winrate_white": winrate_white,
        "winrate_black": winrate_black,
        "overall_top_opening": overall_top_opening,
        "white_top_opening": white_top_opening,
        "black_top_opening": black_top_opening,
        "top_openings_white": top_openings_white,
        "top_openings_black": top_openings_black,
    }


# --- Streamlit Layout ---
tab = st.sidebar.radio("Navigate", ["Dashboard", "Player Stats"])

if tab == "Dashboard":
    st.title("♟️ Chess Rating Dashboard")

    # Retrieve data from Google Sheets
    current, history = fetch_current_and_history()
    df_cur = pd.DataFrame(current)
    st.subheader("Current Ratings")
    st.dataframe(df_cur, use_container_width=True)

    st.subheader("Rating Progression")

    # Prepare the historical ratings data
    df_hist = pd.DataFrame(history)
    df_hist["Date"] = pd.to_datetime(df_hist["Date"])
    df_hist["Day"] = df_hist["Date"].dt.date

    # --- Sidebar Filters for Dashboard ---
    # Multi-select players
    unique_players = sorted(df_hist["Player Name"].unique().tolist())
    selected_players = st.sidebar.multiselect(
        "Filter by Player", unique_players, default=unique_players
    )

    # Single-select filter for Category
    unique_categories = sorted(df_hist["Category"].unique().tolist())
    selected_category = st.sidebar.selectbox(
        "Filter by Category", ["All Categories"] + unique_categories
    )

    # Date range filter
    min_date = df_hist["Day"].min()
    max_date = df_hist["Day"].max()
    selected_dates = st.sidebar.date_input("Select date range", [min_date, max_date])
    if isinstance(selected_dates, (list, tuple)) and len(selected_dates) == 2:
        start_date, end_date = selected_dates
    else:
        start_date, end_date = min_date, max_date

    # Apply filters to the historical data
    mask = (df_hist["Day"] >= start_date) & (df_hist["Day"] <= end_date)
    if selected_players:
        mask &= df_hist["Player Name"].isin(selected_players)
    if selected_category != "All Categories":
        mask &= df_hist["Category"] == selected_category

    df_filtered = df_hist.loc[mask]

    # Group filtered data for the Altair chart
    daily = df_filtered.groupby(["Day", "Player Name", "Category"]).last().reset_index()

    # Create Altair line chart for rating progression
    chart = (
        alt.Chart(daily)
        .mark_line(point=True)
        .encode(
            x=alt.X(
                "Day:T", title="Date", timeUnit="yearmonthdate"
            ),  # Ensures grouping by full date (no hourly breakdown)
            y=alt.Y("Rating:Q", title="Rating"),
            color=alt.Color("Player Name:N", title="Player"),
            strokeDash=alt.StrokeDash("Category:N", title="Category"),
            tooltip=["Day:T", "Player Name:N", "Category:N", "Rating:Q"],
        )
    )
    st.altair_chart(chart, use_container_width=True)

elif tab == "Player Stats":
    st.title("📊 Player Stats")
    choice = st.selectbox("Choose a player", [name for name, _ in FRIENDS])
    username = next(user for name, user in FRIENDS if name == choice)

    avatar_url = get_chesscom_avatar(username)
    if avatar_url:
        st.image(avatar_url, width=100, caption=f"{choice}'s Avatar")

    with st.spinner("Fetching stats..."):
        stats_data = compute_player_stats(username)

    st.subheader(f"{choice}'s Stats")
    st.markdown("### Overall Win Rates (from Chess.com Stats)")
    st.markdown(f"- **Rapid:** {stats_data['overall_rates'].get('rapid', 'N/A')}")
    st.markdown(f"- **Blitz:** {stats_data['overall_rates'].get('blitz', 'N/A')}")
    st.markdown(f"- **Bullet:** {stats_data['overall_rates'].get('bullet', 'N/A')}")

    st.markdown("### Win Rates (Archive Analysis)")
    st.markdown(f"- **White:** {stats_data['winrate_white']}")
    st.markdown(f"- **Black:** {stats_data['winrate_black']}")

    st.markdown("### Top Openings (Archive Analysis)")
    st.markdown(
        f"- **Overall Most Played Opening (last 4 months):** {stats_data['overall_top_opening']}"
    )
    st.markdown(f"- **White's Most Played Opening:** {stats_data['white_top_opening']}")
    st.markdown(f"- **Black's Most Played Opening:** {stats_data['black_top_opening']}")

    st.subheader("Top 5 Openings")
    col1, col2 = st.columns(2)
    with col1:
        st.markdown("**White**")
        if stats_data["top_openings_white"]:
            df_white = pd.DataFrame(
                stats_data["top_openings_white"], columns=["Opening", "Games"]
            )
            bar_white = (
                alt.Chart(df_white)
                .mark_bar()
                .encode(
                    x=alt.X("Games:Q", title="Games Played"),
                    y=alt.Y("Opening:N", sort="-x", title="Opening Name"),
                    tooltip=["Opening", "Games"],
                )
            )
            st.altair_chart(bar_white, use_container_width=True)
        else:
            st.write("No data")
    with col2:
        st.markdown("**Black**")
        if stats_data["top_openings_black"]:
            df_black = pd.DataFrame(
                stats_data["top_openings_black"], columns=["Opening", "Games"]
            )
            bar_black = (
                alt.Chart(df_black)
                .mark_bar()
                .encode(
                    x=alt.X("Games:Q", title="Games Played"),
                    y=alt.Y("Opening:N", sort="-x", title="Opening Name"),
                    tooltip=["Opening", "Games"],
                )
            )
            st.altair_chart(bar_black, use_container_width=True)
        else:
            st.write("No data")

    st.caption(
        "Openings detected using Lichess ECO dataset fallback. Archive analysis spans the last 4 months."
    )

    st.subheader(f"{choice}'s Rating Progression")
    # Retrieve the player's historical ratings only
    current, history = fetch_current_and_history()
    df_hist = pd.DataFrame(history)
    df_hist = df_hist[df_hist["Player Name"] == choice]
    df_hist["Date"] = pd.to_datetime(df_hist["Date"])
    df_hist["Day"] = df_hist["Date"].dt.date
    df_hist["Day"] = pd.to_datetime(df_hist["Date"]).dt.floor(
        "D"
    )  # Forces date-only grouping
daily = df_hist.groupby(["Day", "Category"], as_index=False).agg({"Rating": "mean"})

chart = (
    alt.Chart(daily)
    .mark_line(point=True)
    .encode(
        x=alt.X("Day:T", title="Date", timeUnit="yearmonthdate"),
        y=alt.Y("Rating:Q", title="Rating"),
        color=alt.Color("Category:N", title="Category"),
        tooltip=["Day:T", "Category:N", "Rating:Q"],
    )
)
st.altair_chart(chart, use_container_width=True)
