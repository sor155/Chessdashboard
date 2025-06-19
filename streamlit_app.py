import streamlit as st
import gspread
from google.oauth2.service_account import Credentials
import pandas as pd
import altair as alt
import requests
from datetime import datetime, date
from collections import Counter
import io
import chess
import chess.pgn
import chess.svg
from datasets import load_dataset
import asyncio
import httpx
import time
import json
import traceback

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

# --- UI HELPER FUNCTIONS ---
def create_eval_bar(evaluation):
    """Creates an HTML evaluation bar."""
    if evaluation is None:
        evaluation = 0
    
    # Clamp evaluation for display purposes
    clamped_eval = max(-1000, min(1000, evaluation))
    
    # Convert evaluation to a percentage (0-100)
    # 50% is equal, >50% is white advantage, <50% is black advantage
    percentage = 50 + (clamped_eval / 20)
    
    bar_html = f"""
    <div style="background-color: #333; border: 1px solid #555; height: 25px; width: 100%; border-radius: 5px; overflow: hidden;">
        <div style="background-color: white; height: 100%; width: {percentage}%;"></div>
    </div>
    <div style="text-align: center; color: white; font-size: 0.9em;">{evaluation/100.0:.2f}</div>
    """
    return bar_html

# --- Load Lichess ECO dataset ---
@st.cache_resource
def load_opening_maps():
    try:
        ds = load_dataset("Lichess/chess-openings", split="train")
        eco_map = {row["eco"]: row["name"] for row in ds}
        pgn_map = {row["pgn"]: row["name"] for row in ds}
        return eco_map, pgn_map
    except Exception as e:
        st.error(f"Could not load opening dataset: {e}")
        return {}, {}

eco_map, pgn_map = load_opening_maps()

# --- Chess.com avatar fetch ---
def get_chesscom_avatar(username):
    try:
        r = requests.get(f"https://api.chess.com/pub/player/{username}", headers=HEADERS)
        r.raise_for_status()
        return r.json().get("avatar", None)
    except Exception as e:
        st.warning(f"Could not fetch avatar for {username}: {e}")
        return None

# --- Google Sheets Access ---
@st.cache_data(ttl=3600)
def fetch_current_and_history():
    try:
        if not all(k in st.secrets.get("creds_json", {}) for k in ["type", "project_id", "private_key"]):
            st.error("Your secrets.toml file is missing or incomplete. Please check the format.")
            return [], []
        
        creds = Credentials.from_service_account_info(st.secrets["creds_json"], scopes=SCOPES)
        client = gspread.authorize(creds)
        ss = client.open_by_url(SHEET_URL)
        curr = ss.worksheet("Current Ratings").get_all_records()
        hist = ss.worksheet("Rating History").get_all_records()
        return curr, hist
    except gspread.exceptions.SpreadsheetNotFound:
        st.error("Spreadsheet not found. Please check the SHEET_URL and ensure your service account has access.")
        return [], []
    except Exception as e:
        st.error(f"Could not access Google Sheets: {e}")
        return [], []

# --- ASYNCHRONOUS Chess.com API Helpers ---
async def fetch_url_async(client, url):
    try:
        response = await client.get(url, headers=HEADERS)
        response.raise_for_status()
        return response.json()
    except httpx.HTTPStatusError as e:
        st.warning(f"Could not fetch data from {url}. Status code: {e.response.status_code}")
        return {}
    except Exception as e:
        st.warning(f"Error fetching {url}: {e}")
        return {}

async def fetch_player_stats_async(username):
    try:
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
    except Exception as e:
        st.error(f"Error fetching player stats for {username}: {e}")
        return {}, []

# --- PGN parsing ---
def get_opening_from_pgn(pgn_text):
    try:
        game = chess.pgn.read_game(io.StringIO(pgn_text))
        if not game:
            return "N/A"
        
        eco = game.headers.get("ECO")
        if eco and eco in eco_map:
            return eco_map[eco]
        
        board = game.board()
        moves = []
        for move in game.mainline_moves():
            moves.append(board.san(move))
            board.push(move)
        
        move_seq = " ".join(moves[:10])
        for pgn_prefix, name in pgn_map.items():
            if move_seq.startswith(pgn_prefix):
                return name
        return "N/A"
    except Exception as e:
        st.warning(f"Error parsing PGN for opening: {e}")
        return "N/A"

# --- Player Stats Calculation ---
@st.cache_data(ttl=86400, show_spinner="Fetching player statistics...")
def compute_player_stats(username):
    try:
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
            if opening_name: 
                overall_opening_counts[opening_name] += 1
            
            white_info = g.get("white", {})
            black_info = g.get("black", {})
            accuracies = g.get("accuracies")
            
            if white_info.get("username", "").lower() == username_lower:
                total_white += 1
                if white_info.get("result") == "win": 
                    wins_white += 1
                if opening_name: 
                    white_opening_counts[opening_name] += 1
                if accuracies and accuracies.get("white"): 
                    white_accuracies.append(accuracies.get("white"))
            elif black_info.get("username", "").lower() == username_lower:
                total_black += 1
                if black_info.get("result") == "win": 
                    wins_black += 1
                if opening_name: 
                    black_opening_counts[opening_name] += 1
                if accuracies and accuracies.get("black"): 
                    black_accuracies.append(accuracies.get("black"))
                
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
    except Exception as e:
        st.error(f"Error computing player stats: {e}")
        return {
            "overall_rates": {"rapid": "N/A", "blitz": "N/A", "bullet": "N/A"},
            "winrate_white": "N/A", "winrate_black": "N/A",
            "avg_accuracy_white": "N/A", "avg_accuracy_black": "N/A",
            "overall_top_opening": "N/A", "white_top_opening": "N/A", "black_top_opening": "N/A",
            "top_openings_white": [], "top_openings_black": []
        }

# --- GAME ANALYSIS FUNCTIONS ---
def generate_move_comment(move_data):
    """Generates a human-readable comment for a move."""
    quality = move_data['move_quality']
    best_move = move_data['best_move']
    played_move = move_data['move']
    eval_loss = move_data['eval_loss']

    if quality == "Excellent":
        return "Excellent! You found the best move." if played_move == best_move else "An excellent move! Keeps the advantage."
    elif quality == "Good":
        return "A good move."
    elif quality == "Inaccuracy":
        return f"This is an inaccuracy. The best move was {best_move}, which was slightly better."
    elif quality == "Mistake":
        return f"A mistake. You missed the better move, {best_move}. This move loses an advantage of {eval_loss:.2f} pawns."
    elif quality == "Blunder":
        return f"A major blunder! This move changes the outcome of the game. The best move was {best_move}."
    return ""

@st.cache_data(ttl=3600, show_spinner="Analyzing game with cloud engine...")
def analyze_game_with_api(pgn_data, depth=18):
    try:
        game = chess.pgn.read_game(io.StringIO(pgn_data))
        if not game:
            st.error("❌ Invalid PGN format.")
            return None, None, None

        game_info = {
            'white': game.headers.get('White', 'Unknown'),
            'black': game.headers.get('Black', 'Unknown'),
            'event': game.headers.get('Event', 'Unknown'),
            'date': game.headers.get('Date', 'Unknown'),
            'result': game.headers.get('Result', '*'),
            'eco': game.headers.get('ECO', ''),
            'opening': game.headers.get('Opening', ''),
        }

        board = game.board()
        analysis_data = []
        board_states = [board.fen()]
        
        moves = list(game.mainline_moves())
        total_moves = len(moves)
        progress_bar = st.progress(0)
        status_text = st.empty()

        for i, move in enumerate(moves):
            try:
                turn = "White" if board.turn == chess.WHITE else "Black"
                status_text.text(f"Analyzing move {i + 1}/{total_moves} ({turn}'s turn)...")
                progress_bar.progress((i + 1) / total_moves)

                fen_before = board.fen()
                api_response_before = requests.post("https://chess-api.com/v1", json={"fen": fen_before, "depth": depth})
                api_response_before.raise_for_status()
                data_before = api_response_before.json()
                eval_before = data_before.get('eval')
                best_move_san = data_before.get('bestmove')

                actual_move_san = board.san(move)
                board.push(move)
                board_states.append(board.fen())

                fen_after = board.fen()
                api_response_after = requests.post("https://chess-api.com/v1", json={"fen": fen_after, "depth": depth})
                api_response_after.raise_for_status()
                data_after = api_response_after.json()
                eval_after = data_after.get('eval')

                if eval_before is not None and eval_after is not None:
                    eval_loss = (eval_before - eval_after) if turn == "White" else (eval_after - eval_before)
                else:
                    eval_loss = 0

                if eval_loss < 20: move_quality = "Excellent"
                elif eval_loss < 50: move_quality = "Good"
                elif eval_loss < 100: move_quality = "Inaccuracy"
                elif eval_loss < 200: move_quality = "Mistake"
                else: move_quality = "Blunder"
                
                move_analysis = {
                    'ply': i + 1,
                    'move_number': (i // 2) + 1,
                    'color': turn,
                    'move': actual_move_san,
                    'best_move': best_move_san,
                    'eval_before': eval_before,
                    'eval_after': eval_after,
                    'eval_loss': eval_loss / 100.0,
                    'move_quality': move_quality,
                }
                move_analysis['comment'] = generate_move_comment(move_analysis)
                analysis_data.append(move_analysis)

            except Exception as e:
                st.warning(f"Analysis for move {i + 1} failed: {e}")
                continue

        progress_bar.empty()
        status_text.empty()
        return game_info, analysis_data, board_states

    except Exception as e:
        st.error(f"🔥 Unexpected error during API analysis:\n```\n{traceback.format_exc()}\n```")
        return None, None, None

# --- Test PGN Data ---
TEST_PGN = """[Event "Live Chess"]
[Site "Chess.com"]
[Date "2024.01.15"]
[Round "-"]
[White "TestPlayer1"]
[Black "TestPlayer2"]
[Result "1-0"]
[ECO "C65"]
[WhiteElo "1500"]
[BlackElo "1480"]
[TimeControl "600"]
[EndTime "14:32:18 PST"]
[Termination "TestPlayer1 won by checkmate"]

1. e4 e5 2. Nf3 Nc6 3. Bb5 Nf6 4. d3 Bc5 5. O-O d6 6. c3 a6 7. Ba4 b5 8. Bb3 O-O 9. h3 h6 10. Re1 Re8 11. Nbd2 Be6 12. Bc2 d5 13. exd5 Bxd5 14. Ne4 Nxe4 15. dxe4 Be6 16. Qe2 Qf6 17. Be3 Bxe3 18. Qxe3 Rad8 19. a4 Bc4 20. b3 Be6 21. axb5 axb5 22. Qc5 Bxh3 23. Qxb5 Bg4 24. Nh2 Bd7 25. Qe2 Ne7 26. Ra7 Qb6 27. Rea1 Ng6 28. g3 Bb5 29. c4 Bc6 30. R1a6 Qc5 31. Rxc7 Re6 32. b4 Qd6 33. Raa7 Be8 34. c5 Qd2 35. Qxd2 Rxd2 36. Ba4 Bxa4 37. Rxa4 Re7 38. Rc8+ Kh7 39. b5 Rb2 40. b6 Rd7 41. Ra7 Rd1+ 42. Kg2 Rbb1 43. b7 Rg1+ 44. Kf3 Rb3+ 45. Ke2 Rgb1 46. c6 Ne7 47. Re8 Nxc6 48. Rc7 Nd4+ 49. Kd2 R1b2+ 50. Kc1 Ne2+ 51. Kd1 Nc3+ 52. Kc1 Na2+ 53. Kd1 Rxb7 54. Rxb7 Rxb7 55. Rxe5 Nc3+ 56. Kd2 Nb1+ 57. Kd3 Na3 58. f4 Rd7+ 59. Ke3 Nc4+ 60. Kf3 Nxe5+ 61. fxe5 Re7 62. Kf4 g5+ 63. Kf5 Kg7 64. Ng4 Re6 65. Nf6 Ra6 66. g4 Ra1 67. Nh5+ Kf8 68. Kf6 Ra6+ 69. Kf5 Ke7 70. Nf6 Ra1 71. Ng8+ Kf8 72. Nxh6 Rf1+ 73. Kxg5 Ke7 74. Nf5+ Ke6 75. Ng7+ Kxe5 76. Kh6 Kxe4 77. g5 Rh1+ 78. Nh5 Kf5 79. g6 fxg6 80. Kg7 Rxh5 81. Kf7 g5 1-0"""

# --- Streamlit Layout ---
tab = st.sidebar.radio("Navigate", ["Dashboard", "Player Stats", "Game Analysis"])

# --- Initialize Session State ---
if 'player_choice' not in st.session_state: st.session_state.player_choice = FRIENDS[0][0]
if 'analysis_results' not in st.session_state: st.session_state.analysis_results = None
if 'board_states' not in st.session_state: st.session_state.board_states = None
if 'pgn_text' not in st.session_state: st.session_state.pgn_text = ""
if 'current_ply' not in st.session_state: st.session_state.current_ply = 0

# --- Dashboard Tab ---
if tab == "Dashboard":
    st.title("♟️ Chess Rating Dashboard")
    try:
        current, history = fetch_current_and_history()
        st.subheader("Current Ratings")
        if current:
            st.dataframe(pd.DataFrame(current), use_container_width=True)
        else:
            st.warning("No current ratings data available. Check your Google Sheet and secrets file.")
        
        st.subheader("Rating Progression")
        if history:
            df_hist = pd.DataFrame(history)
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
            if selected_players: 
                mask &= df_hist["Player Name"].isin(selected_players)
            if selected_category != "All Categories": 
                mask &= df_hist["Category"] == selected_category
            df_filtered = df_hist.loc[mask]
            daily = df_filtered.groupby(["Day", "Player Name", "Category"]).last().reset_index()
            chart = alt.Chart(daily).mark_line(point=True).encode(
                x=alt.X("Day:T", title="Date"), 
                y=alt.Y("Rating:Q", title="Rating"), 
                color=alt.Color("Player Name:N"), 
                strokeDash=alt.StrokeDash("Category:N"), 
                tooltip=["Day:T", "Player Name:N", "Category:N", "Rating:Q"]
            ).interactive()
            st.altair_chart(chart, use_container_width=True)
        else:
            st.warning("No rating history data available.")
    except Exception as e:
        st.error(f"Error loading dashboard: {e}")

# --- Player Stats Tab ---
elif tab == "Player Stats":
    st.title("📊 Player Stats")
    try:
        choice = st.selectbox("Choose a player", [name for name, _ in FRIENDS], key='player_choice')
        username = next(user for name, user in FRIENDS if name == choice)
        avatar_url = get_chesscom_avatar(username)
        if avatar_url: 
            st.image(avatar_url, width=100, caption=f"{choice}'s Avatar")
        
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
        if history:
            df_hist = pd.DataFrame(history)
            df_player_hist = df_hist[df_hist["Player Name"] == choice]
            if not df_player_hist.empty:
                df_player_hist["Date"] = pd.to_datetime(df_player_hist["Date"])
                df_player_hist["Day"] = df_player_hist["Date"].dt.date
                player_chart = alt.Chart(df_player_hist).mark_line(point=True).encode(
                    x=alt.X("Day:T"), 
                    y=alt.Y("Rating:Q"), 
                    color=alt.Color("Category:N"), 
                    tooltip=["Day:T", "Category:N", "Rating:Q"]
                ).interactive()
                st.altair_chart(player_chart, use_container_width=True)
    except Exception as e:
        st.error(f"Error loading player stats: {e}")

# --- Game Analysis Tab ---
elif tab == "Game Analysis":
    st.title("🔍 Game Analysis")
    st.markdown("Paste the PGN of a game below to get a full computer analysis from a cloud engine.")

    col1, col2 = st.columns([3, 1])
    with col1:
        pgn_text_input = st.text_area("Paste PGN Here:", value=st.session_state.pgn_text, height=250, placeholder="[Event \"Live Chess\"]...")
    with col2:
        st.markdown("**Quick Test:**")
        if st.button("Load Test PGN", help="Load a sample PGN for testing"):
            st.session_state.pgn_text = TEST_PGN
            st.rerun()

    with st.expander("Analysis Settings"):
        depth = st.slider("Analysis Depth", 10, 22, 18, help="Higher depth is more accurate but much slower. The free API is best at depth 18.")

    col1, col2 = st.columns(2)
    with col1:
        if st.button("🔍 Analyze Game", type="primary"):
            if not pgn_text_input.strip():
                st.error("Please paste a PGN to analyze.")
            else:
                st.session_state.pgn_text = pgn_text_input
                st.session_state.current_ply = 0
                game_info, analysis, boards = analyze_game_with_api(pgn_text_input, depth)
                if game_info and analysis and boards:
                    st.session_state.analysis_results = (game_info, analysis)
                    st.session_state.board_states = boards
                    st.balloons()
                else:
                    st.error("Could not analyze game. Check PGN or API status.")
    with col2:
        if st.button("🗑️ Clear Analysis"):
            st.session_state.analysis_results = None
            st.session_state.board_states = None
            st.session_state.pgn_text = ""
            st.session_state.current_ply = 0
            st.rerun()
    
    if st.session_state.analysis_results:
        game_info, analysis_data = st.session_state.analysis_results
        
        st.header("📋 Game Review")
        
        board_col, comment_col = st.columns([1, 1])
        
        with board_col:
            board = chess.Board(st.session_state.board_states[st.session_state.current_ply])
            st.image(chess.svg.board(board=board, size=400))
            
            # Display eval bar
            current_eval = analysis_data[st.session_state.current_ply -1]['eval_after'] if st.session_state.current_ply > 0 else 0
            st.markdown(create_eval_bar(current_eval), unsafe_allow_html=True)
            
            nav_cols = st.columns(2)
            if nav_cols[0].button("⬅️ Previous", use_container_width=True):
                if st.session_state.current_ply > 0:
                    st.session_state.current_ply -= 1
                    st.rerun()
            if nav_cols[1].button("Next ➡️", use_container_width=True):
                if st.session_state.current_ply < len(st.session_state.board_states) - 1:
                    st.session_state.current_ply += 1
                    st.rerun()

        with comment_col:
            current_ply = st.session_state.current_ply
            
            # Display player names
            st.markdown(f"**White:** {game_info['white']} | **Black:** {game_info['black']}")
            st.divider()

            if current_ply > 0:
                move_data = analysis_data[current_ply - 1]
                st.subheader(f"Move {move_data['move_number']}: {move_data['color']}")
                st.markdown(f"#### You played **{move_data['move']}**")
                
                quality = move_data['move_quality']
                if quality == "Excellent": st.success(f"**{quality}!** {move_data['comment']}")
                elif quality == "Good": st.info(f"**{quality}.** {move_data['comment']}")
                elif quality == "Inaccuracy": st.warning(f"**{quality}.** {move_data['comment']}")
                else: st.error(f"**{quality}!** {move_data['comment']}")
            else:
                st.subheader("Starting Position")
                st.info("Use the buttons to navigate through the game review.")
        
        st.divider()

        st.header("🔍 Move List")
        df_display = pd.DataFrame(analysis_data)
        st.dataframe(df_display[['move_number', 'color', 'move', 'eval_after', 'move_quality', 'comment']], use_container_width=True)

        csv = df_display.to_csv(index=False)
        st.download_button("📥 Download Full Analysis (CSV)", csv, f"analysis_{game_info['white']}_vs_{game_info['black']}.csv")