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
import json  # MISSING IMPORT - This was causing the error

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
        creds = Credentials.from_service_account_file("credentials.json", scopes=SCOPES)
        client = gspread.authorize(creds)
        ss = client.open_by_url(SHEET_URL)
        curr = ss.worksheet("Current Ratings").get_all_records()
        hist = ss.worksheet("Rating History").get_all_records()
        return curr, hist
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

# --- STOCKFISH ANALYSIS FUNCTIONS ---
import chess.engine
import subprocess
import os

def find_stockfish_path():
    """Find Stockfish executable in common locations"""
    possible_paths = [
        "stockfish",  # If in PATH
        "/usr/bin/stockfish",  # Linux
        "/usr/local/bin/stockfish",  # macOS with Homebrew
        "/opt/homebrew/bin/stockfish",  # macOS with Apple Silicon Homebrew
        "C:\\Program Files\\Stockfish\\stockfish.exe",  # Windows
        "C:\\stockfish\\stockfish.exe",  # Windows alternative
        "./stockfish",  # Local directory
        "./stockfish.exe",  # Local directory Windows
    ]
    
    for path in possible_paths:
        try:
            result = subprocess.run([path, "--help"], capture_output=True, timeout=5)
            if result.returncode == 0:
                return path
        except (subprocess.TimeoutExpired, FileNotFoundError, subprocess.SubprocessError):
            continue
    
    return None

@st.cache_data(ttl=3600, show_spinner="Analyzing game with Stockfish...")
def analyze_game_with_stockfish(pgn_data, depth=20, time_limit=1.0):
    """
    Analyze a chess game using Stockfish engine
    
    Args:
        pgn_data: PGN string of the game
        depth: Analysis depth (higher = more accurate but slower)
        time_limit: Time limit per move in seconds
    
    Returns:
        tuple: (game_info, analysis_data) or (None, None) if error
    """
    try:
        # Find Stockfish
        stockfish_path = find_stockfish_path()
        if not stockfish_path:
            st.error("""
            Stockfish engine not found. Please install Stockfish:
            
            **Linux/Ubuntu:** `sudo apt-get install stockfish`
            **macOS:** `brew install stockfish`
            **Windows:** Download from https://stockfishchess.org/download/
            
            Or ensure stockfish is in your PATH.
            """)
            return None, None
        
        # Parse the PGN
        try:
            game = chess.pgn.read_game(io.StringIO(pgn_data))
            if not game:
                st.error("Invalid PGN format. Please check your PGN data.")
                return None, None
        except Exception as e:
            st.error(f"PGN parsing error: {e}")
            return None, None
        
        # Extract game information
        game_info = {
            'white': game.headers.get('White', 'Unknown'),
            'black': game.headers.get('Black', 'Unknown'),
            'event': game.headers.get('Event', 'Unknown'),
            'date': game.headers.get('Date', 'Unknown'),
            'result': game.headers.get('Result', '*'),
            'eco': game.headers.get('ECO', ''),
            'opening': game.headers.get('Opening', ''),
        }
        
        # Initialize Stockfish engine
        with chess.engine.SimpleEngine.popen_uci(stockfish_path) as engine:
            board = game.board()
            moves = list(game.mainline_moves())
            analysis_data = []
            
            total_moves = len(moves)
            progress_bar = st.progress(0)
            status_text = st.empty()
            
            # Analyze each position
            for i, move in enumerate(moves):
                status_text.text(f"Analyzing move {i + 1}/{total_moves}: {board.san(move)}")
                progress_bar.progress((i + 1) / total_moves)
                
                # Get evaluation before the move
                try:
                    info = engine.analyse(board, chess.engine.Limit(depth=depth, time=time_limit))
                    score = info.get("score")
                    
                    if score:
                        # Convert score to centipawns from White's perspective
                        if score.is_mate():
                            if board.turn == chess.WHITE:
                                eval_cp = 10000 if score.white().mate() > 0 else -10000
                                mate_in = abs(score.white().mate())
                            else:
                                eval_cp = -10000 if score.white().mate() > 0 else 10000
                                mate_in = abs(score.white().mate())
                        else:
                            eval_cp = score.white().score()
                            mate_in = None
                    else:
                        eval_cp = 0
                        mate_in = None
                    
                    # Get best move
                    best_move = info.get("pv", [None])[0]
                    best_move_san = board.san(best_move) if best_move else ""
                    
                    # Make the actual move
                    actual_move_san = board.san(move)
                    board.push(move)
                    
                    # Get evaluation after the move
                    post_move_info = engine.analyse(board, chess.engine.Limit(depth=depth, time=time_limit))
                    post_score = post_move_info.get("score")
                    
                    if post_score:
                        if post_score.is_mate():
                            post_eval_cp = 10000 if post_score.white().mate() > 0 else -10000
                        else:
                            post_eval_cp = post_score.white().score()
                    else:
                        post_eval_cp = 0
                    
                    # Calculate move quality
                    eval_loss = abs(post_eval_cp - eval_cp) if eval_cp is not None and post_eval_cp is not None else 0
                    
                    # Classify move quality
                    if eval_loss < 10:
                        move_quality = "Excellent"
                        quality_symbol = "!!"
                    elif eval_loss < 25:
                        move_quality = "Good"
                        quality_symbol = "!"
                    elif eval_loss < 50:
                        move_quality = "Inaccuracy"
                        quality_symbol = "?!"
                    elif eval_loss < 100:
                        move_quality = "Mistake"
                        quality_symbol = "?"
                    else:
                        move_quality = "Blunder"
                        quality_symbol = "??"
                    
                    analysis_entry = {
                        'move_number': (i // 2) + 1,
                        'color': 'White' if i % 2 == 0 else 'Black',
                        'move': actual_move_san,
                        'best_move': best_move_san,
                        'eval_before': eval_cp,
                        'eval_after': post_eval_cp,
                        'eval_loss': eval_loss,
                        'mate_in': mate_in,
                        'move_quality': move_quality,
                        'quality_symbol': quality_symbol,
                        'is_best_move': actual_move_san == best_move_san
                    }
                    
                    analysis_data.append(analysis_entry)
                    
                except Exception as e:
                    st.warning(f"Error analyzing move {i + 1}: {e}")
                    continue
            
            progress_bar.empty()
            status_text.empty()
            
            return game_info, analysis_data
            
    except Exception as e:
        st.error(f"Unexpected error during Stockfish analysis: {e}")
        return None, None

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

1. e4 e5 2. Nf3 Nc6 3. Bb5 Nf6 4. d3 Bc5 5. Bxc6 dxc6 6. h3 Nd7 7. Nc3 f5 8. exf5 Nf6 9. g4 h6 10. Bg5 hxg5 11. Nxg5 Rh4 12. f3 Qd4 13. Qe2 Bxf5 14. gxf5 Qf2+ 15. Qxf2 Bxf2+ 16. Kxf2 Rxh3 17. Nxh3 Nxf5 18. Rg1 O-O-O 19. Rg5 Rd2+ 20. Kg3 Rxc2 21. Rxf5 Rxb2 22. Rxe5 Rxa2 23. Re8+ Kd7 24. Re7+ Kd6 25. Rxg7 Ra3 26. Rg6+ Ke7 27. Rxc6 Rxc3 28. Rxc7+ Kf6 29. Rc6+ Kg5 30. f4+ Kh5 31. Rc5+ Kg6 32. Rc6+ Kf7 33. Rc7+ Ke6 34. Re7+ Kf6 35. Re4 Rc1 36. f5 Rf1 37. Re6+ Kf7 38. Re7+ Kf8 39. Re8+ Kf7 40. Re7+ Kg8 41. Re8+ Kh7 42. f6 Rf3+ 43. Kg4 Rf4+ 44. Kg5 Rf5+ 45. Kg4 Rf4+ 46. Kh5 Rf5+ 47. Kg4 Rf4+ 48. Kh5 Rf2 49. f7 Kg7 50. Re7 Rf5+ 51. Kg4 Rf4+ 52. Kg3 Rf3+ 53. Kg2 Rf2+ 54. Kh1 Rf1+ 55. Kg2 Rf2+ 56. Kg3 Rf3+ 57. Kg4 Rf4+ 58. Kg5 Rf5+ 59. Kg4 Rf1 60. f8=Q+ Kh7 61. Qf7+ Kh8 62. Nf4 Rf3 63. Re8# 1-0"""

# --- Streamlit Layout ---
tab = st.sidebar.radio("Navigate", ["Dashboard", "Player Stats", "Game Analysis"])

if 'player_choice' not in st.session_state:
    st.session_state.player_choice = FRIENDS[0][0]

if tab == "Dashboard":
    st.title("♟️ Chess Rating Dashboard")
    try:
        current, history = fetch_current_and_history()
        st.subheader("Current Ratings")
        if current:
            st.dataframe(pd.DataFrame(current), use_container_width=True)
        else:
            st.warning("No current ratings data available.")
        
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

elif tab == "Game Analysis":
    st.title("🔍 Game Analysis")
    st.markdown("Paste the PGN of a game below to get a full computer analysis from Lichess.")
    
    col1, col2 = st.columns([3, 1])
    with col1:
        pgn_text = st.text_area("Paste PGN Here:", height=200, placeholder="[Event \"Live Chess\"]...")
    with col2:
        st.markdown("**Quick Test:**")
        if st.button("Load Test PGN", help="Load a sample PGN for testing"):
            st.session_state.test_pgn = TEST_PGN
            st.rerun()
    
    # Load test PGN if button was clicked
    if 'test_pgn' in st.session_state:
        pgn_text = st.session_state.test_pgn
        del st.session_state.test_pgn
    
    # Analysis settings
    with st.expander("Analysis Settings", expanded=False):
        col1, col2 = st.columns(2)
        with col1:
            depth = st.slider("Analysis Depth", min_value=10, max_value=25, value=18, 
                            help="Higher depth = more accurate but slower analysis")
        with col2:
            time_limit = st.slider("Time per Move (seconds)", min_value=0.5, max_value=5.0, value=1.0, step=0.5,
                                 help="More time = more accurate but slower analysis")
    
    col1, col2 = st.columns([1, 1])
    with col1:
        analyze_button = st.button("🔍 Analyze with Stockfish", type="primary")
    with col2:
        clear_button = st.button("🗑️ Clear PGN")
    
    if clear_button:
        st.rerun()
    
    if analyze_button:
        if not pgn_text.strip():
            st.error("Please paste a valid PGN into the text area.")
        else:
            game_info, analysis_data = analyze_game_with_stockfish(pgn_text, depth=depth, time_limit=time_limit)
            if game_info and analysis_data:
                st.success("✅ Analysis complete!")
                
                # Game Information
                st.subheader("📋 Game Information")
                info_col1, info_col2 = st.columns(2)
                with info_col1:
                    st.markdown(f"**White:** {game_info['white']}")
                    st.markdown(f"**Black:** {game_info['black']}")
                    st.markdown(f"**Result:** {game_info['result']}")
                with info_col2:
                    st.markdown(f"**Event:** {game_info['event']}")
                    st.markdown(f"**Date:** {game_info['date']}")
                    if game_info['eco']:
                        st.markdown(f"**ECO:** {game_info['eco']}")
                
                # Analysis Summary
                st.subheader("📊 Analysis Summary")
                total_moves = len(analysis_data)
                excellent_moves = sum(1 for move in analysis_data if move['move_quality'] == 'Excellent')
                good_moves = sum(1 for move in analysis_data if move['move_quality'] == 'Good')
                inaccuracies = sum(1 for move in analysis_data if move['move_quality'] == 'Inaccuracy')
                mistakes = sum(1 for move in analysis_data if move['move_quality'] == 'Mistake')
                blunders = sum(1 for move in analysis_data if move['move_quality'] == 'Blunder')
                
                summary_col1, summary_col2, summary_col3, summary_col4, summary_col5 = st.columns(5)
                with summary_col1:
                    st.metric("Excellent Moves", excellent_moves, f"{excellent_moves/total_moves*100:.1f}%")
                with summary_col2:
                    st.metric("Good Moves", good_moves, f"{good_moves/total_moves*100:.1f}%")
                with summary_col3:
                    st.metric("Inaccuracies", inaccuracies, f"{inaccuracies/total_moves*100:.1f}%")
                with summary_col4:
                    st.metric("Mistakes", mistakes, f"{mistakes/total_moves*100:.1f}%")
                with summary_col5:
                    st.metric("Blunders", blunders, f"{blunders/total_moves*100:.1f}%")
                
                # Move-by-Move Analysis
                st.subheader("🔍 Move-by-Move Analysis")
                
                # Filter options
                filter_col1, filter_col2 = st.columns(2)
                with filter_col1:
                    show_only_mistakes = st.checkbox("Show only mistakes/blunders", value=False)
                with filter_col2:
                    show_best_moves = st.checkbox("Show suggested best moves", value=True)
                
                # Prepare data for display
                display_data = []
                for entry in analysis_data:
                    if show_only_mistakes and entry['move_quality'] in ['Excellent', 'Good']:
                        continue
                    
                    eval_before = f"{entry['eval_before']/100:.2f}" if entry['eval_before'] is not None else "N/A"
                    eval_after = f"{entry['eval_after']/100:.2f}" if entry['eval_after'] is not None else "N/A"
                    
                    if entry['mate_in']:
                        eval_display = f"Mate in {entry['mate_in']}"
                    else:
                        eval_display = eval_before
                    
                    move_display = f"{entry['move']} {entry['quality_symbol']}"
                    if show_best_moves and not entry['is_best_move'] and entry['best_move']:
                        move_display += f" (Best: {entry['best_move']})"
                    
                    display_row = {
                        "Move": f"{entry['move_number']}. {entry['color']}",
                        "Played": move_display,
                        "Evaluation": eval_display,
                        "Eval Change": f"{entry['eval_loss']/100:.2f}" if entry['eval_loss'] else "0.00",
                        "Quality": f"{entry['move_quality']} {entry['quality_symbol']}"
                    }
                    display_data.append(display_row)
                
                if display_data:
                    df_analysis = pd.DataFrame(display_data)
                    
                    # Color code the dataframe based on move quality
                    def highlight_moves(row):
                        quality = row['Quality']
                        if 'Blunder' in quality:
                            return ['background-color: #ffebee'] * len(row)
                        elif 'Mistake' in quality:
                            return ['background-color: #fff3e0'] * len(row)
                        elif 'Inaccuracy' in quality:
                            return ['background-color: #fffde7'] * len(row)
                        elif 'Excellent' in quality:
                            return ['background-color: #e8f5e8'] * len(row)
                        else:
                            return [''] * len(row)
                    
                    styled_df = df_analysis.style.apply(highlight_moves, axis=1)
                    st.dataframe(styled_df, use_container_width=True)
                    
                    # Download analysis as CSV
                    csv = df_analysis.to_csv(index=False)
                    st.download_button(
                        label="📥 Download Analysis as CSV",
                        data=csv,
                        file_name=f"chess_analysis_{game_info['white']}_vs_{game_info['black']}.csv",
                        mime="text/csv"
                    )
                    
                    st.balloons()
                else:
                    st.info("No moves match the current filter criteria.")
            else:
                st.error("Could not analyze the game. Please check your PGN format and ensure Stockfish is installed.")