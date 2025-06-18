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
import asyncio
import httpx
import time

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
        r = requests.get(f"https://api.chess.com/pub/player/{username}", headers=HEADERS)
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

# --- ASYNCHRONOUS Chess.com API Helpers ---
async def fetch_url_async(client, url):
    try:
        response = await client.get(url, headers=HEADERS)
        response.raise_for_status()
        return response.json()
    except httpx.HTTPStatusError as e:
        st.warning(f"Could not fetch data from {url}. Status code: {e.response.status_code}")
        return {}

async def fetch_player_stats_async(username):
    async with httpx.AsyncClient() as client:
        stats_task = fetch_url_async(client, f"https://api.chess.com/pub/player/{username}/stats")
        archives_list_task = fetch_url_async(client, f"https://api.chess.com/pub/player/{username}/games/archives")
        stats_data, archives_list_data = await asyncio.gather(stats_task, archives_list_task)
        archive_urls = archives_list_data.get("archives", [])[-4:]
        game_tasks = [fetch_url_async(client, url) for url in archive_urls]
        monthly_games_responses = await asyncio.gather(*game_tasks)
        all_games = []
        for response in monthly_games_responses:
            all_games.extend(response.get("games", []))
        return stats_data, all_games

# --- PGN parsing ---
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

# --- Player Stats Calculation ---
@st.cache_data(ttl=86400, show_spinner=True)
def compute_player_stats(username):
    stats, all_games = asyncio.run(fetch_player_stats_async(username))
    overall_rates = {}
    for cat in ["rapid", "blitz", "bullet"]:
        rec = stats.get(f"chess_{cat}", {}).get("record", {})
        w, l, d = rec.get("win", 0), rec.get("loss", 0), rec.get("draw", 0)
        total = w + l + d
        overall_rates[cat] = f"{100 * w / total:.1f}%" if total > 0 else "N/A"
    
    overall_opening_counts = Counter()
    wins_white, total_white, white_accuracies = 0, 0, []
    wins_black, total_black, black_accuracies = 0, 0, []
    white_opening_counts, black_opening_counts = Counter(), Counter()
    username_lower = username.lower()

    for g in all_games:
        opening_name = g.get("opening", {}).get("name") or get_opening_from_pgn(g.get("pgn", ""))
        if opening_name: overall_opening_counts[opening_name] += 1
        white_info = g.get("white", {})
        black_info = g.get("black", {})
        accuracies = g.get("accuracies")
        if white_info.get("username", "").lower() == username_lower:
            total_white += 1
            if white_info.get("result") == "win": wins_white += 1
            if opening_name: white_opening_counts[opening_name] += 1
            if accuracies and accuracies.get("white"): white_accuracies.append(accuracies.get("white"))
        elif black_info.get("username", "").lower() == username_lower:
            total_black += 1
            if black_info.get("result") == "win": wins_black += 1
            if opening_name: black_opening_counts[opening_name] += 1
            if accuracies and accuracies.get("black"): black_accuracies.append(accuracies.get("black"))
            
    return {
        "overall_rates": overall_rates,
        "winrate_white": f"{100 * wins_white / total_white:.1f}%" if total_white > 0 else "N/A",
        "winrate_black": f"{100 * wins_black / total_black:.1f}%" if total_black > 0 else "N/A",
        "avg_accuracy_white": f"{sum(white_accuracies) / len(white_accuracies):.1f}%" if white_accuracies else "N/A",
        "avg_accuracy_black": f"{sum(black_accuracies) / len(black_accuracies):.1f}%" if black_accuracies else "N/A",
        "overall_top_opening": overall_opening_counts.most_common(1)[0][0] if overall_opening_counts else "N/A",
        "white_top_opening": white_opening_counts.most_common(1)[0][0] if white_opening_counts else "N/A",
        "black_top_opening": black_opening_counts.most_common(1)[0][0] if black_opening_counts else "N/A",
        "top_openings_white": white_opening_counts.most_common(5),
        "top_openings_black": black_opening_counts.most_common(5),
    }

# --- GAME ANALYSIS FUNCTIONS ---
@st.cache_data(ttl=3600, show_spinner="Requesting Lichess analysis...")
def get_lichess_analysis_data(pgn_data):
    try:
        import_headers = {"Accept": "application/json"}
        import_response = requests.post("https://lichess.org/api/import", data={'pgn': pgn_data}, headers=import_headers)
        import_response.raise_for_status()
        import_json = import_response.json()
        game_id = import_json.get('id')

        if not game_id:
            st.error("Lichess API did not return a game ID from the import.")
            return None, None
        
        time.sleep(2)

        analysis_headers = {"Accept": "application/x-ndjson"}
        analysis_url = f"https://lichess.org/api/game/export/{game_id}"
        
        for attempt in range(5):
            analysis_response = requests.get(analysis_url, params={"evals": "true", "clocks": "false"}, headers=analysis_headers)
            if analysis_response.status_code == 200:
                lines = analysis_response.text.strip().split('\n')
                game_info = json.loads(lines[0])
                analysis_info = json.loads(lines[1]) if len(lines) > 1 else {}
                return game_info, analysis_info.get('analysis')
            time.sleep(3)
        
        st.error("Could not retrieve analysis from Lichess after multiple attempts.")
        return None, None

    except Exception as e:
        st.error(f"Could not get Lichess analysis. Error: {e}")
        return None, None

# --- Streamlit Layout ---
tab = st.sidebar.radio("Navigate", ["Dashboard", "Player Stats", "Game Analysis"])

if 'player_choice' not in st.session_state:
    st.session_state.player_choice = FRIENDS[0][0]

if tab == "Dashboard":
    st.title("♟️ Chess Rating Dashboard")
    current, history = fetch_current_and_history()
    st.subheader("Current Ratings")
    st.dataframe(pd.DataFrame(current), use_container_width=True)
    
    st.subheader("Rating Progression")
    df_hist = pd.DataFrame(history)
    if not df_hist.empty:
        df_hist["Date"] = pd.to_datetime(df_hist["Date"])
        df_hist["Day"] = df_hist["Date"].dt.date
        unique_players = sorted(df_hist["Player Name"].unique().tolist())
        selected_players = st.sidebar.multiselect("Filter by Player", unique_players, default=unique_players)
        unique_categories = sorted(df_hist["Category"].unique().tolist())
        selected_category = st.sidebar.selectbox("Filter by Category", ["All Categories"] + unique_categories)
        min_date, max_date = df_hist["Day"].min(), df_hist["Day"].max()
        selected_dates = st.sidebar.date_input("Select date range", [min_date, max_date])
        start_date, end_date = (selected_dates[0], selected_dates[1]) if len(selected_dates) == 2 else (min_date, max_date)
        mask = (df_hist["Day"] >= start_date) & (df_hist["Day"] <= end_date)
        if selected_players: mask &= df_hist["Player Name"].isin(selected_players)
        if selected_category != "All Categories": mask &= df_hist["Category"] == selected_category
        df_filtered = df_hist.loc[mask]
        daily = df_filtered.groupby(["Day", "Player Name", "Category"]).last().reset_index()
        chart = alt.Chart(daily).mark_line(point=True).encode(x=alt.X("Day:T", title="Date"), y=alt.Y("Rating:Q", title="Rating"), color=alt.Color("Player Name:N"), strokeDash=alt.StrokeDash("Category:N"), tooltip=["Day:T", "Player Name:N", "Category:N", "Rating:Q"]).interactive()
        st.altair_chart(chart, use_container_width=True)

elif tab == "Player Stats":
    st.title("📊 Player Stats")
    choice = st.selectbox("Choose a player", [name for name, _ in FRIENDS], key='player_choice')
    username = next(user for name, user in FRIENDS if name == choice)
    avatar_url = get_chesscom_avatar(username)
    if avatar_url: st.image(avatar_url, width=100, caption=f"{choice}'s Avatar")
    stats_data = compute_player_stats(username)
    st.subheader(f"{choice}'s Stats")
    st.markdown("### Overall Win Rates (from Chess.com Stats)")
    st.markdown(f"- **Rapid:** {stats_data['overall_rates'].get('rapid', 'N/A')}")
    st.markdown(f"- **Blitz:** {stats_data['overall_rates'].get('blitz', 'N/A')}")
    st.markdown(f"- **Bullet:** {stats_data['overall_rates'].get('bullet', 'N/A')}")
    st.markdown("### Win Rates (Last 4 Months)")
    st.markdown(f"- **White:** {stats_data['winrate_white']}")
    st.markdown(f"- **Black:** {stats_data['winrate_black']}")
    st.markdown("### Average Accuracy (Last 4 Months)")
    st.markdown(f"- **As White:** {stats_data['avg_accuracy_white']}")
    st.markdown(f"- **As Black:** {stats_data['avg_accuracy_black']}")
    st.markdown("### Top Openings (Last 4 Months)")
    st.markdown(f"- **Overall:** {stats_data['overall_top_opening']}")
    st.markdown(f"- **As White:** {stats_data['white_top_opening']}")
    st.markdown(f"- **As Black:** {stats_data['black_top_opening']}")
    st.subheader("Top 5 Openings")
    col1, col2 = st.columns(2)
    with col1:
        st.markdown("**White**")
        if stats_data["top_openings_white"]:
            st.dataframe(pd.DataFrame(stats_data["top_openings_white"], columns=["Opening", "Games"]), use_container_width=True)
    with col2:
        st.markdown("**Black**")
        if stats_data["top_openings_black"]:
            st.dataframe(pd.DataFrame(stats_data["top_openings_black"], columns=["Opening", "Games"]), use_container_width=True)
    st.subheader(f"{choice}'s Rating Progression")
    _, history = fetch_current_and_history()
    df_hist = pd.DataFrame(history)
    df_player_hist = df_hist[df_hist["Player Name"] == choice]
    if not df_player_hist.empty:
        df_player_hist["Date"] = pd.to_datetime(df_player_hist["Date"])
        df_player_hist["Day"] = df_player_hist["Date"].dt.date
        player_chart = alt.Chart(df_player_hist).mark_line(point=True).encode(x=alt.X("Day:T"), y=alt.Y("Rating:Q"), color=alt.Color("Category:N"), tooltip=["Day:T", "Category:N", "Rating:Q"]).interactive()
        st.altair_chart(player_chart, use_container_width=True)

elif tab == "Game Analysis":
    st.title("🔍 Game Analysis")
    st.markdown("Paste the PGN of a game below to get a full computer analysis from Lichess.")
    pgn_text = st.text_area("Paste PGN Here:", height=200, placeholder="[Event \"Live Chess\"]...")
    if st.button("Analyze Game"):
        if not pgn_text.strip():
            st.error("Please paste a valid PGN into the text area.")
        else:
            game_info, analysis_data = get_lichess_analysis_data(pgn_text)
            if game_info and analysis_data:
                game_id = game_info.get('id')
                embed_url = f"https://lichess.org/embed/{game_id}?theme=auto&bg=auto"
                st.success("Analysis board is ready!")
                st.components.v1.iframe(embed_url, height=450, scrolling=True)
                st.subheader("Move-by-Move Analysis")
                moves_list = []
                for i, entry in enumerate(analysis_data):
                    move_number = (i // 2) + 1
                    turn = "White" if i % 2 == 0 else "Black"
                    move_info = {
                        "Move": f"{move_number}. {turn}",
                        "Notation": entry.get('move'),
                        "Evaluation": entry.get('eval') / 100.0 if 'eval' in entry else "N/A",
                        "Comment": entry.get('judgment', {}).get('comment', '')
                    }
                    moves_list.append(move_info)
                df_analysis = pd.DataFrame(moves_list)
                st.dataframe(df_analysis, use_container_width=True)
                st.balloons()
