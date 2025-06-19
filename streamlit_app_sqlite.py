import streamlit as st
import pandas as pd
import altair as alt
import requests
from datetime import date
import sqlite3
import chess
import chess.pgn
import chess.svg
import io
from stockfish import Stockfish
import traceback
import asyncio
import httpx
from collections import Counter
from datasets import load_dataset

# --- PAGE CONFIG ---
st.set_page_config(layout="wide", page_title="Chess Dashboard")

# --- CONFIGURATION ---
DB_NAME = "chess_ratings.db"
FRIENDS = [
    ("Ulysse", "realulysse"),
    ("Simon", "poulet_tao"),
    ("Adrien", "adrienbourque"),
    ("Alex", "naatiry"),
    ("Kevin", "kevor24"),
]
HEADERS = {"User-Agent": "ChessDashboard/4.0-Final"}

# --- SESSION STATE INITIALIZATION (THE FIX) ---
# This block is crucial and must run before the UI is drawn.
if 'analysis_results' not in st.session_state:
    st.session_state.analysis_results = None
if 'board_states' not in st.session_state:
    st.session_state.board_states = None
if 'pgn_text' not in st.session_state:
    st.session_state.pgn_text = ""
if 'current_ply' not in st.session_state:
    st.session_state.current_ply = 0
# --- END OF FIX ---

# --- LOAD OPENING DATASET ---
@st.cache_resource
def load_opening_maps():
    """Loads and caches the Lichess opening dataset."""
    try:
        ds = load_dataset("Lichess/chess-openings", split="train")
        pgn_map = {row["pgn"]: row["name"] for row in ds}
        return pgn_map
    except Exception as e:
        st.error(f"Could not load the chess openings dataset: {e}")
        return {}

pgn_to_opening_map = load_opening_maps()

# --- ROBUST OPENING DETECTION ---
def get_opening_name(game_data):
    """Determines the opening name using a multi-step, robust method."""
    pgn_text = game_data.get("pgn", "")
    if not pgn_text: return "Unknown"
    
    # Method 1: Check the direct 'opening' field in the JSON from Chess.com.
    if "opening" in game_data and isinstance(game_data["opening"], dict) and "name" in game_data["opening"]:
        return game_data["opening"]["name"]

    # Method 2: Check the PGN headers.
    pgn_headers = chess.pgn.read_headers(io.StringIO(pgn_text))
    if pgn_headers and "Opening" in pgn_headers:
        return pgn_headers["Opening"]

    # Method 3: Analyze the actual move sequence.
    try:
        game = chess.pgn.read_game(io.StringIO(pgn_text))
        if not game: return "Unknown"
        
        moves = [board.san(move) for board in game.board().move_stack]
        if len(moves) > 10: moves = moves[:10]
        move_sequence = " ".join(moves)
        
        for pgn_prefix, name in pgn_to_opening_map.items():
            if move_sequence.startswith(pgn_prefix):
                return name
    except Exception:
        return "Unknown"

    return "Unknown"

# --- LIVE STATS ANALYSIS ---
@st.cache_data(ttl=3600, show_spinner="Fetching latest player stats from Chess.com...")
def get_live_player_analysis(username):
    async def fetch_and_compute():
        async with httpx.AsyncClient() as client:
            profile_task = client.get(f"https://api.chess.com/pub/player/{username}", headers=HEADERS)
            archives_task = client.get(f"https://api.chess.com/pub/player/{username}/games/archives", headers=HEADERS)
            profile_res, archives_res = await asyncio.gather(profile_task, archives_task)
            
            if profile_res.is_error or archives_res.is_error: return {"error": "Failed to fetch data from Chess.com API."}, None

            avatar_url = profile_res.json().get("avatar")
            archive_urls = archives_res.json().get("archives", [])[-4:]

            if not archive_urls: return {"error": "No game archives found."}, avatar_url

            game_responses = await asyncio.gather(*[client.get(url, headers=HEADERS) for url in archive_urls])
            all_games = [game for res in game_responses if not res.is_error for game in res.json().get("games", [])]

            if not all_games: return {"error": "No games found in recent archives."}, avatar_url

            stats = {"wins_white": 0, "total_white": 0, "white_accuracies": [], "wins_black": 0, "total_black": 0, "black_accuracies": [], "white_openings": Counter(), "black_openings": Counter()}
            username_lower = username.lower()

            for g in all_games:
                if g.get('rules') != 'chess': continue
                opening_name = get_opening_name(g)
                white, black = g.get("white", {}), g.get("black", {})
                accuracies = g.get("accuracies", {})

                if white.get("username", "").lower() == username_lower:
                    stats["total_white"] += 1
                    if white.get("result") == "win": stats["wins_white"] += 1
                    if opening_name != "Unknown": stats["white_openings"][opening_name] += 1
                    if "white" in accuracies: stats["white_accuracies"].append(accuracies["white"])

                elif black.get("username", "").lower() == username_lower:
                    stats["total_black"] += 1
                    if black.get("result") == "win": stats["wins_black"] += 1
                    if opening_name != "Unknown": stats["black_openings"][opening_name] += 1
                    if "black" in accuracies: stats["black_accuracies"].append(accuracies["black"])

            return {
                "winrate_white": f"{100 * stats['wins_white'] / stats['total_white']:.1f}%" if stats['total_white'] > 0 else "N/A",
                "winrate_black": f"{100 * stats['wins_black'] / stats['total_black']:.1f}%" if stats['total_black'] > 0 else "N/A",
                "avg_accuracy_white": f"{sum(stats['white_accuracies']) / len(stats['white_accuracies']):.1f}%" if stats['white_accuracies'] else "N/A",
                "avg_accuracy_black": f"{sum(stats['black_accuracies']) / len(stats['black_accuracies']):.1f}%" if stats['black_accuracies'] else "N/A",
                "top_openings_white": stats["white_openings"].most_common(5),
                "top_openings_black": stats["black_openings"].most_common(5),
            }, avatar_url

    return asyncio.run(fetch_and_compute())


# --- All other functions and UI code are included below without modification ---
# ... [The rest of the file: database access, game analysis, UI helpers, and layout] ...

@st.cache_data(ttl=60)
def fetch_from_db(table_name):
    try:
        with sqlite3.connect(DB_NAME) as conn:
            df = pd.read_sql_query(f"SELECT * FROM {table_name}", conn)
            return df
    except sqlite3.OperationalError as e:
        st.error(f"Database error: {e}. Make sure the database file '{DB_NAME}' exists and the table '{table_name}' is created. You may need to run `database_setup.py`.")
        return pd.DataFrame()

def generate_move_comment(move_data):
    quality = move_data['move_quality']
    if quality == "Excellent": return "Excellent! You found the best move."
    if quality == "Good": return "A good move, maintaining the advantage."
    if quality == "Inaccuracy": return f"An inaccuracy. The best move was {move_data['best_move']}."
    if quality == "Mistake": return f"A mistake. You missed the better move: {move_data['best_move']}."
    if quality == "Blunder": return f"A major blunder! This move changes the game. The best move was {move_data['best_move']}."
    return ""

@st.cache_data(ttl=3600, show_spinner="Analyzing game with local engine...")
def analyze_game_with_stockfish(pgn_data, stockfish_path="/usr/bin/stockfish"):
    try:
        stockfish = Stockfish(path=stockfish_path, parameters={"Threads": 2, "Hash": 256})
    except Exception as e:
        st.error(f"Could not initialize Stockfish from path: {stockfish_path}. Error: {e}")
        return None, None, None

    try:
        game = chess.pgn.read_game(io.StringIO(pgn_data))
        if not game: return None, None, None

        game_info = dict(game.headers)
        board = game.board()
        analysis_data, board_states = [], [board.fen()]
        moves = list(game.mainline_moves())
        progress_bar, status_text = st.progress(0), st.empty()

        for i, move in enumerate(moves):
            turn = "White" if board.turn == chess.WHITE else "Black"
            status_text.text(f"Analyzing move {i + 1}/{len(moves)} ({turn}'s turn)...")
            
            stockfish.set_fen_position(board.fen())
            eval_before = stockfish.get_evaluation().get('value')
            best_move_uci = stockfish.get_best_move()
            best_move_san = board.san(chess.Move.from_uci(best_move_uci)) if best_move_uci else "N/A"
            
            board.push(move)
            board_states.append(board.fen())
            stockfish.set_fen_position(board.fen())
            eval_after = stockfish.get_evaluation().get('value')
            
            eval_loss = 0
            if isinstance(eval_before, int) and isinstance(eval_after, int):
                eval_loss = (eval_before - eval_after) if turn == "White" else (eval_after - eval_before)

            if eval_loss < 20: quality = "Excellent"
            elif eval_loss < 50: quality = "Good"
            elif eval_loss < 100: quality = "Inaccuracy"
            elif eval_loss < 200: quality = "Mistake"
            else: quality = "Blunder"
            
            move_analysis = {
                'ply': i + 1, 'move_number': (i // 2) + 1, 'color': turn,
                'move': board.san(move), 'best_move': best_move_san,
                'eval_before': eval_before, 'eval_after': eval_after,
                'eval_loss': eval_loss / 100.0, 'move_quality': quality,
            }
            move_analysis['comment'] = generate_move_comment(move_analysis)
            analysis_data.append(move_analysis)
            progress_bar.progress((i + 1) / len(moves))

        progress_bar.empty()
        status_text.empty()
        return game_info, analysis_data, board_states
    except Exception as e:
        st.error(f"🔥 Unexpected error during analysis:\n```\n{traceback.format_exc()}\n```")
        return None, None, None

def create_eval_bar(evaluation):
    if evaluation is None: evaluation = 0
    clamped_eval = max(-1000, min(1000, evaluation))
    percentage = 50 + (clamped_eval / 20)
    eval_in_pawns = evaluation / 100.0
    bar_html = f"""
    <div style="position: relative; background-color: #333; border: 1px solid #555; height: 25px; width: 100%; border-radius: 5px; overflow: hidden;">
        <div style="background-color: white; height: 100%; width: {percentage}%;"></div>
        <div style="position: absolute; top: 0; left: 0; width: 100%; height: 100%; text-align: center; color: {'black' if 40 < percentage < 60 else 'white'}; line-height: 25px; font-size: 0.9em;">
            Eval: {eval_in_pawns:.2f}
        </div>
    </div>
    """
    return bar_html

tab = st.sidebar.radio("Navigate", ["Dashboard", "Player Stats", "Game Analysis"])

if tab == "Dashboard":
    st.title("♟️ Chess Rating Dashboard")
    st.subheader("Current Ratings (From Database)")
    df_current = fetch_from_db("current_ratings")
    if not df_current.empty:
        st.dataframe(df_current.set_index('friend_name'), use_container_width=True)
    else:
        st.warning("No ratings data found. Run `update_tracker_sqlite.py` to populate the database.")
    st.subheader("Rating Progression")
    df_history = fetch_from_db("rating_history")
    if not df_history.empty:
        df_history["Date"] = pd.to_datetime(df_history["timestamp"])
        df_history["Day"] = df_history["Date"].dt.date
        unique_players = sorted(df_history["player_name"].unique().tolist())
        selected_players = st.sidebar.multiselect("Filter by Player", unique_players, default=unique_players)
        unique_categories = sorted(df_history["category"].unique().tolist())
        selected_category = st.sidebar.selectbox("Filter by Category", ["All Categories"] + unique_categories)
        min_date, max_date = df_history["Day"].min(), df_history["Day"].max()
        selected_dates = st.sidebar.date_input("Select date range", [min_date, max_date])
        start_date, end_date = selected_dates if len(selected_dates) == 2 else (min_date, max_date)
        mask = (df_history["Day"].between(start_date, end_date)) & \
               (df_history["player_name"].isin(selected_players)) & \
               (df_history["category"] == selected_category if selected_category != "All Categories" else True)
        daily = df_history[mask].groupby(["Day", "player_name", "category"]).last().reset_index()
        chart = alt.Chart(daily).mark_line(point=True).encode(
            x=alt.X("Day:T", title="Date"), y=alt.Y("rating:Q", title="Rating"),
            color=alt.Color("player_name:N", title="Player"),
            strokeDash=alt.StrokeDash("category:N", title="Category"),
            tooltip=["Day:T", "player_name:N", "category:N", "rating:Q"]
        ).interactive()
        st.altair_chart(chart, use_container_width=True)

elif tab == "Player Stats":
    st.title("📊 Player Stats")
    choice = st.selectbox("Choose a player", [name for name, _ in FRIENDS], key='player_choice')
    username = next(user for name, user in FRIENDS if name == choice)
    stats_data, avatar_url = get_live_player_analysis(username)
    col1, col2 = st.columns([1, 5])
    with col1:
        if avatar_url: st.image(avatar_url, width=100)
    with col2:
        st.header(choice)
        st.markdown(f"*{username} on Chess.com*")
    if "error" in stats_data:
        st.error(f"Could not retrieve live analysis for {choice}. Reason: {stats_data['error']}")
    else:
        st.subheader("Performance by Color (Last 4 Months)")
        c1, c2 = st.columns(2)
        with c1:
            st.metric("Win Rate as White", stats_data['winrate_white'])
            st.metric("Avg Accuracy as White", stats_data['avg_accuracy_white'])
        with c2:
            st.metric("Win Rate as Black", stats_data['winrate_black'])
            st.metric("Avg Accuracy as Black", stats_data['avg_accuracy_black'])
        st.subheader("Favorite Openings (Last 4 Months)")
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("**As White**")
            df_white = pd.DataFrame(stats_data["top_openings_white"], columns=["Opening", "Games"])
            st.dataframe(df_white, use_container_width=True, hide_index=True)
        with c2:
            st.markdown("**As Black**")
            df_black = pd.DataFrame(stats_data["top_openings_black"], columns=["Opening", "Games"])
            st.dataframe(df_black, use_container_width=True, hide_index=True)
    st.subheader(f"{choice}'s Rating Progression (From Database)")
    df_player_hist = fetch_from_db("rating_history")
    if not df_player_hist.empty:
        df_player_hist = df_player_hist[df_player_hist["player_name"] == choice]
        if not df_player_hist.empty:
            df_player_hist["Date"] = pd.to_datetime(df_player_hist["timestamp"])
            player_chart = alt.Chart(df_player_hist).mark_line(point=True).encode(
                x=alt.X("Date:T", title="Date"), y=alt.Y("rating:Q", title="Rating"),
                color=alt.Color("category:N", title="Category"),
                tooltip=["Date:T", "category:N", "rating:Q"]
            ).interactive()
            st.altair_chart(player_chart, use_container_width=True)
        else:
            st.info(f"No rating history for {choice} found in the database.")

elif tab == "Game Analysis":
    st.title("🔍 Game Analysis")
    st.markdown("Paste the PGN of a game below to get a full computer analysis.")
    pgn_text_input = st.text_area("Paste PGN Here:", value=st.session_state.pgn_text, height=250)
    c1, c2 = st.columns(2)
    if c1.button("Analyze Game", type="primary", use_container_width=True):
        if pgn_text_input.strip():
            st.session_state.pgn_text = pgn_text_input
            st.session_state.current_ply = 0
            info, analysis, boards = analyze_game_with_stockfish(pgn_text_input)
            if info and analysis and boards:
                st.session_state.analysis_results = (info, analysis)
                st.session_state.board_states = boards
                st.rerun()
        else:
            st.error("Please paste a PGN to analyze.")
    if c2.button("Clear Analysis", use_container_width=True):
        st.session_state.analysis_results = None
        st.session_state.board_states = None
        st.session_state.pgn_text = ""
        st.session_state.current_ply = 0
        st.rerun()
    if st.session_state.analysis_results:
        game_info, analysis_data = st.session_state.analysis_results
        st.header("📋 Game Review")
        board_col, comment_col = st.columns([1, 1.2])
        with board_col:
            board = chess.Board(st.session_state.board_states[st.session_state.current_ply])
            st.image(chess.svg.board(board=board, size=400), use_container_width=True)
            current_eval = analysis_data[st.session_state.current_ply - 1]['eval_after'] if st.session_state.current_ply > 0 else 20
            st.markdown(create_eval_bar(current_eval), unsafe_allow_html=True)
            nav_cols = st.columns(2)
            if nav_cols[0].button("⬅️ Previous", use_container_width=True, disabled=st.session_state.current_ply == 0):
                st.session_state.current_ply -= 1
                st.rerun()
            if nav_cols[1].button("Next ➡️", use_container_width=True, disabled=st.session_state.current_ply >= len(st.session_state.board_states) - 1):
                st.session_state.current_ply += 1
                st.rerun()
        with comment_col:
            st.markdown(f"**White:** {game_info.get('White', 'N/A')} | **Black:** {game_info.get('Black', 'N/A')} | **Result:** {game_info.get('Result', '*')}")
            st.divider()
            if st.session_state.current_ply > 0:
                move_data = analysis_data[st.session_state.current_ply - 1]
                st.subheader(f"Move {move_data['move_number']}: {move_data['color']}")
                st.markdown(f"#### You played **{move_data['move']}**")
                quality = move_data['move_quality']
                if quality == "Excellent": st.success(f"**{quality}!** {move_data['comment']}")
                elif quality == "Good": st.info(f"**{quality}.** {move_data['comment']}")
                elif quality == "Inaccuracy": st.warning(f"**{quality}.** {move_data['comment']}")
                else: st.error(f"**{quality}!** {move_data['comment']}")
            else:
                st.subheader("Starting Position")
                st.info("Use the navigation buttons to step through the game.")
        st.divider()
        st.header("🔍 Full Move List Analysis")
        df_display = pd.DataFrame(analysis_data)
        st.dataframe(df_display[['move_number', 'color', 'move', 'best_move', 'eval_loss', 'move_quality']], use_container_width=True, hide_index=True)
        csv = df_display.to_csv(index=False)
        st.download_button("📥 Download Analysis (CSV)", csv, f"analysis_{game_info.get('White', 'N/A')}_vs_{game_info.get('Black', 'N/A')}.csv", "text/csv")