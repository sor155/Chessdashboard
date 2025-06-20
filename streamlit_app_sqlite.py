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
import os

# --- PAGE CONFIG AND CONSTANTS ---
st.set_page_config(layout="wide", page_title="Chess Dashboard")
DB_NAME = "chess_ratings.db"
FRIENDS = [
    ("Ulysse", "realulysse"), ("Simon", "poulet_tao"), ("Adrien", "adrienbourque"),
    ("Alex", "naatiry"), ("Kevin", "kevor24"),
]
HEADERS = {"User-Agent": "ChessDashboard/Final-v12.0"}

# --- STOCKFISH PATH CONFIGURATION ---
def get_stockfish_path():
    """Determines the correct path for the Stockfish executable."""
    # Path for deployed Streamlit Cloud environment via packages.txt
    linux_path = "/usr/games/stockfish"
    if os.path.exists(linux_path):
        return linux_path
    
    # Path for your local Windows environment
    windows_path = "C:/Users/theso/OneDrive/Desktop/Chess test/stockfish.exe"
    if os.path.exists(windows_path):
        return windows_path
        
    # Fallback for other Linux distributions
    alt_linux_path = "/usr/bin/stockfish"
    if os.path.exists(alt_linux_path):
        return alt_linux_path

    # If neither is found, return None
    return None

STOCKFISH_PATH = get_stockfish_path()

# --- SESSION STATE INITIALIZATION ---
if 'analysis_results' not in st.session_state: st.session_state.analysis_results = None
if 'board_states' not in st.session_state: st.session_state.board_states = None
if 'pgn_text' not in st.session_state: st.session_state.pgn_text = ""
if 'current_ply' not in st.session_state: st.session_state.current_ply = 0

# --- DATA LOADING ---
@st.cache_resource
def load_opening_maps():
    """Loads and caches the Lichess opening dataset."""
    try:
        ds = load_dataset("Lichess/chess-openings", split="train")
        eco_map = {row["eco"]: row["name"] for row in ds}
        pgn_map = {row["pgn"]: row["name"] for row in ds}
        return eco_map, pgn_map
    except Exception as e:
        st.error(f"Fatal: Could not load the chess openings dataset. Opening analysis will be unavailable. Error: {e}")
        return None, None
eco_map, pgn_map = load_opening_maps()

@st.cache_data(ttl=60)
def fetch_from_db(table_name):
    """Fetches data from the specified SQLite table."""
    try:
        with sqlite3.connect(DB_NAME) as conn: return pd.read_sql_query(f"SELECT * FROM {table_name}", conn)
    except sqlite3.OperationalError:
        st.error(f"Database error: The table '{table_name}' was not found. Please run `database_setup.py` and `update_tracker_sqlite.py`.")
        return pd.DataFrame()

# --- CORE LOGIC ---
def get_opening_name(game_data):
    """Determines the opening name using a multi-step, robust method."""
    if not eco_map or not pgn_map: return "Unknown (Dataset unavailable)"
    pgn_text = game_data.get("pgn")
    if not pgn_text: return "Unknown"
    try:
        pgn_headers = chess.pgn.read_headers(io.StringIO(pgn_text))
        if not pgn_headers: return "Unknown"
        eco = pgn_headers.get("ECO");
        if eco and eco in eco_map: return eco_map[eco]
        opening = pgn_headers.get("Opening");
        if opening: return opening
        game = chess.pgn.read_game(io.StringIO(pgn_text))
        if not game: return "Unknown"
        board, moves_san, last_known_opening = game.board(), [], "Unknown"
        for move in game.mainline_moves():
            moves_san.append(board.san(move)); board.push(move)
            current_sequence = " ".join(moves_san)
            if current_sequence in pgn_map: last_known_opening = pgn_map[current_sequence]
            if len(moves_san) >= 15: break
        return last_known_opening
    except Exception: return "Unknown"

@st.cache_data(ttl=3600, show_spinner="Fetching latest player stats from Chess.com...")
def get_live_player_analysis(username):
    """Fetches and computes detailed player stats by analyzing recent game archives."""
    async def fetch_and_compute():
        async with httpx.AsyncClient() as client:
            profile_task = client.get(f"https://api.chess.com/pub/player/{username}", headers=HEADERS)
            archives_task = client.get(f"https://api.chess.com/pub/player/{username}/games/archives", headers=HEADERS)
            profile_res, archives_res = await asyncio.gather(profile_task, archives_task)
            if profile_res.is_error or archives_res.is_error: return {"error": "API request failed."}, None
            avatar_url, archive_urls = profile_res.json().get("avatar"), archives_res.json().get("archives", [])[-4:]
            if not archive_urls: return {"error": "No game archives found."}, avatar_url
            game_responses = await asyncio.gather(*[client.get(url, headers=HEADERS) for url in archive_urls])
            all_games = [game for res in game_responses if not res.is_error for game in res.json().get("games", [])]
            if not all_games: return {"error": "No games found in recent archives."}, avatar_url
            stats = {"wins_white":0,"total_white":0,"white_accuracies":[],"wins_black":0,"total_black":0,"black_accuracies":[],"white_openings":Counter(),"black_openings":Counter()}
            username_lower = username.lower()
            for g in all_games:
                if g.get('rules') != 'chess': continue
                opening_name = get_opening_name(g)
                white, black, accuracies = g.get("white",{}), g.get("black",{}), g.get("accuracies",{})
                if white.get("username","").lower() == username_lower:
                    stats["total_white"]+=1;
                    if white.get("result")=="win": stats["wins_white"]+=1
                    if opening_name!="Unknown": stats["white_openings"][opening_name]+=1
                    if "white" in accuracies: stats["white_accuracies"].append(accuracies["white"])
                elif black.get("username","").lower() == username_lower:
                    stats["total_black"]+=1;
                    if black.get("result")=="win": stats["wins_black"]+=1
                    if opening_name!="Unknown": stats["black_openings"][opening_name]+=1
                    if "black" in accuracies: stats["black_accuracies"].append(accuracies["black"])
            return {"winrate_white":f"{100*stats['wins_white']/stats['total_white']:.1f}%" if stats['total_white']>0 else "N/A", "winrate_black":f"{100*stats['wins_black']/stats['total_black']:.1f}%" if stats['total_black']>0 else "N/A", "avg_accuracy_white":f"{sum(stats['white_accuracies'])/len(stats['white_accuracies']):.1f}%" if stats['white_accuracies'] else "N/A", "avg_accuracy_black":f"{sum(stats['black_accuracies'])/len(stats['black_accuracies']):.1f}%" if stats['black_accuracies'] else "N/A", "top_openings_white":stats["white_openings"].most_common(5), "top_openings_black":stats["black_openings"].most_common(5)}, avatar_url
    return asyncio.run(fetch_and_compute())

def generate_move_comment(move_data):
    """Generates a more detailed, human-readable comment for a move's quality."""
    quality = move_data['move_quality']
    best_move = move_data['best_move']
    played_move = move_data['move']
    eval_loss = move_data['eval_loss']

    if quality == "Excellent":
        return "Excellent! You found the best move." if played_move == best_move else "An excellent move! Keeps the advantage."
    elif quality == "Good":
        return "A good solid move."
    elif quality == "Inaccuracy":
        return f"An inaccuracy. The best move was {best_move}, which was slightly better."
    elif quality == "Mistake":
        return f"A mistake. You missed the better move, {best_move}. This move loses an advantage of {eval_loss:.2f} pawns."
    elif quality == "Blunder":
        return f"A major blunder! This move significantly worsens your position. The best move was {best_move}."
    return ""

@st.cache_data(ttl=3600, show_spinner="Analyzing game with local engine...")
def analyze_game_with_stockfish(pgn_data):
    """Analyzes a game PGN using a local Stockfish engine."""
    if not STOCKFISH_PATH:
        st.error("Stockfish engine not found. Please ensure it is installed and the path is configured correctly in the script.")
        return None, None, None
    try:
        stockfish = Stockfish(path=STOCKFISH_PATH, parameters={"Threads": 4, "Hash": 1024})
    except Exception as e:
        st.error(f"Could not initialize Stockfish from path '{STOCKFISH_PATH}'. Error: {e}"); return None, None, None
    try:
        game = chess.pgn.read_game(io.StringIO(pgn_data))
        if not game: st.error("Invalid PGN data."); return None, None, None
        game_info, board, analysis, states = dict(game.headers), game.board(), [], [game.board().fen()]
        moves = list(game.mainline_moves())
        progress_bar, status_text = st.progress(0), st.empty()
        
        for i, move in enumerate(moves):
            turn = "White" if board.turn == chess.WHITE else "Black"
            status_text.text(f"Analyzing move {i + 1}/{len(moves)} ({turn}'s turn)...")
            
            move_san = board.san(move)
            
            stockfish.set_fen_position(board.fen())
            eval_before = stockfish.get_evaluation().get('value')
            top_moves = stockfish.get_top_moves(3) # Get top 3 moves
            best_move_san = board.san(chess.Move.from_uci(top_moves[0]['Move'])) if top_moves else "N/A"
            
            board.push(move)
            states.append(board.fen())
            
            stockfish.set_fen_position(board.fen())
            eval_after = stockfish.get_evaluation().get('value')
            
            eval_loss = 0
            if isinstance(eval_before, int) and isinstance(eval_after, int):
                eval_loss = (eval_before - eval_after) if turn=="White" else (eval_after - eval_before)
                
            quality = "Excellent" if eval_loss < 20 else "Good" if eval_loss < 50 else "Inaccuracy" if eval_loss < 100 else "Mistake" if eval_loss < 200 else "Blunder"
            
            move_data = {
                'ply': i + 1, 'move_number': (i // 2) + 1, 'color': turn, 
                'move': move_san, 'best_move': best_move_san, 'eval_before': eval_before,
                'eval_after': eval_after, 'eval_loss': eval_loss / 100.0,
                'move_quality': quality, 'top_moves': top_moves
            }
            move_data['comment'] = generate_move_comment(move_data)
            analysis.append(move_data)
            progress_bar.progress((i + 1) / len(moves))
            
        progress_bar.empty(); status_text.empty()
        return game_info, analysis, states
    except Exception as e:
        st.error(f"🔥 Error during analysis: {e}\n{traceback.format_exc()}"); return None, None, None

def create_eval_bar(evaluation):
    if evaluation is None: evaluation = 0
    clamped_eval = max(-1000, min(1000, evaluation))
    percentage = 50 + (clamped_eval / 20)
    eval_in_pawns = evaluation / 100.0
    return f"""<div style="position:relative;background-color:#333;border:1px solid #555;height:25px;width:100%;border-radius:5px;overflow:hidden;"><div style="background-color:white;height:100%;width:{percentage}%;"></div><div style="position:absolute;top:0;left:0;width:100%;height:100%;text-align:center;color:{'black' if 40<percentage<60 else 'white'};line-height:25px;font-size:0.9em;">Eval: {eval_in_pawns:.2f}</div></div>"""

# --- UI LAYOUT ---
tab = st.sidebar.radio("Navigate", ["Dashboard", "Player Stats", "Game Analysis"])

if tab == "Dashboard":
    st.title("♟️ Chess Rating Dashboard")
    st.subheader("Current Ratings (From Database)")
    df_current = fetch_from_db("current_ratings")
    if not df_current.empty: st.dataframe(df_current.set_index('friend_name'), use_container_width=True)
    else: st.warning("No ratings data found. Run `update_tracker_sqlite.py` to populate the database.")
    st.subheader("Rating Progression")
    df_history = fetch_from_db("rating_history")
    if not df_history.empty:
        df_history["Date"] = pd.to_datetime(df_history["timestamp"])
        df_history["Day"] = df_history["Date"].dt.date
        players = st.sidebar.multiselect("Filter by Player", sorted(df_history["player_name"].unique()), default=sorted(df_history["player_name"].unique()))
        category = st.sidebar.selectbox("Filter by Category", ["All Categories"] + sorted(df_history["category"].unique()))
        min_d, max_d = df_history["Day"].min(), df_history["Day"].max()
        dates = st.sidebar.date_input("Select date range", [min_d, max_d])
        start_d, end_d = (dates[0], dates[1]) if len(dates) == 2 else (min_d, max_d)
        mask = (df_history["Day"].between(start_d, end_d)) & (df_history["player_name"].isin(players)) & (df_history["category"] == category if category != "All Categories" else True)
        chart = alt.Chart(df_history[mask].groupby(["Day","player_name","category"]).last().reset_index()).mark_line(point=True).encode(
            x=alt.X("Day:T", title="Date"), y=alt.Y("rating:Q", title="Rating"),
            color=alt.Color("player_name:N", title="Player"), strokeDash=alt.StrokeDash("category:N", title="Category"),
            tooltip=["Day:T", "player_name:N", "category:N", "rating:Q"]
        ).interactive()
        st.altair_chart(chart, use_container_width=True)

elif tab == "Player Stats":
    st.title("📊 Player Stats")
    if not pgn_map: st.warning("Opening dataset could not be loaded. Opening analysis will be unavailable.", icon="⚠️")
    choice = st.selectbox("Choose a player", [name for name, _ in FRIENDS])
    username = next(user for name, user in FRIENDS if name == choice)
    stats, avatar = get_live_player_analysis(username)
    c1, c2 = st.columns([1, 5])
    if avatar: c1.image(avatar, width=100)
    c2.header(choice); c2.markdown(f"*{username} on Chess.com*")
    if "error" in stats: st.error(f"Could not get live analysis: {stats['error']}")
    else:
        st.subheader("Performance by Color (Last 4 Months)")
        c1, c2 = st.columns(2)
        c1.metric("Win Rate as White", stats['winrate_white']); c1.metric("Avg Accuracy as White", stats['avg_accuracy_white'])
        c2.metric("Win Rate as Black", stats['winrate_black']); c2.metric("Avg Accuracy as Black", stats['avg_accuracy_black'])
        st.subheader("Favorite Openings (Last 4 Months)")
        c1, c2 = st.columns(2)
        c1.markdown("**As White**"); c1.dataframe(pd.DataFrame(stats["top_openings_white"], columns=["Opening", "Games"]), hide_index=True, use_container_width=True)
        c2.markdown("**As Black**"); c2.dataframe(pd.DataFrame(stats["top_openings_black"], columns=["Opening", "Games"]), hide_index=True, use_container_width=True)
    st.subheader(f"{choice}'s Rating Progression (From Database)")
    df_player = fetch_from_db("rating_history")
    if not df_player.empty and not df_player[df_player["player_name"] == choice].empty:
        df_player = df_player[df_player["player_name"] == choice]
        df_player["Date"] = pd.to_datetime(df_player["timestamp"])
        chart = alt.Chart(df_player).mark_line(point=True).encode(
            x=alt.X("Date:T", title="Date"), y=alt.Y("rating:Q", title="Rating"),
            color=alt.Color("category:N", title="Category"), tooltip=["Date:T", "category:N", "rating:Q"]
        ).interactive()
        st.altair_chart(chart, use_container_width=True)

elif tab == "Game Analysis":
    st.title("🔍 Game Analysis")
    st.markdown("Paste PGN to get a full analysis using a local Stockfish engine.")
    st.session_state.pgn_text = st.text_area("Paste PGN Here:", value=st.session_state.pgn_text, height=250)
    c1, c2 = st.columns(2)
    if c1.button("Analyze Game", type="primary", use_container_width=True):
        if st.session_state.pgn_text.strip():
            st.session_state.current_ply = 0
            info, analysis, boards = analyze_game_with_stockfish(st.session_state.pgn_text)
            if info and analysis and boards: st.session_state.analysis_results, st.session_state.board_states = (info, analysis), boards; st.rerun()
        else: st.error("Please paste a PGN to analyze.")
    if c2.button("Clear Analysis", use_container_width=True):
        st.session_state.analysis_results, st.session_state.board_states, st.session_state.pgn_text, st.session_state.current_ply = None, None, "", 0; st.rerun()
    
    if st.session_state.analysis_results:
        info, analysis = st.session_state.analysis_results
        
        # --- RESPONSIVE LAYOUT FOR ANALYSIS ---
        # On wide screens, use columns. On mobile, Streamlit stacks them automatically.
        board_col, comment_col = st.columns([1, 1.3])
        
        with board_col:
            current_board = chess.Board(st.session_state.board_states[st.session_state.current_ply])
            
            # Draw an arrow for the best move
            arrow = []
            if st.session_state.current_ply < len(analysis):
                best_move_uci = analysis[st.session_state.current_ply].get('top_moves', [])[0]['Move']
                move = chess.Move.from_uci(best_move_uci)
                arrow.append(chess.svg.Arrow(move.from_square, move.to_square, color="#6B17CC")) # Green arrow
            
            st.image(chess.svg.board(board=current_board, arrows=arrow, size=400), use_container_width=True)
            
            current_eval = analysis[st.session_state.current_ply - 1]['eval_after'] if st.session_state.current_ply > 0 else 20
            st.markdown(create_eval_bar(current_eval), unsafe_allow_html=True)
            nav1, nav2 = st.columns(2)
            if nav1.button("⬅️ Previous", use_container_width=True, disabled=(st.session_state.current_ply == 0)): st.session_state.current_ply -= 1; st.rerun()
            if nav2.button("Next ➡️", use_container_width=True, disabled=(st.session_state.current_ply >= len(st.session_state.board_states) - 1)): st.session_state.current_ply += 1; st.rerun()
            
        with comment_col:
            st.markdown(f"**White:** {info.get('White', 'N/A')} | **Black:** {info.get('Black', 'N/A')} | **Result:** {info.get('Result', '*')}")
            st.divider()
            
            if st.session_state.current_ply > 0:
                move_data = analysis[st.session_state.current_ply - 1]
                st.subheader(f"Move {move_data['move_number']}: {move_data['color']}")
                st.markdown(f"#### You played **{move_data['move']}**")
                quality = move_data['move_quality']
                if quality == "Excellent": st.success(f"**{quality}!** {move_data['comment']}")
                elif quality == "Good": st.info(f"**{quality}.** {move_data['comment']}")
                elif quality == "Inaccuracy": st.warning(f"**{quality}.** {move_data['comment']}")
                else: st.error(f"**{quality}!** {move_data['comment']}")
                
                # Display Top Engine Lines
                st.markdown("---")
                st.subheader("Engine's Top Choices")
                
                board_before_move = chess.Board(st.session_state.board_states[st.session_state.current_ply - 1])
                top_moves = analysis[st.session_state.current_ply - 1].get('top_moves', [])
                for i, top_move in enumerate(top_moves):
                    move_uci = top_move['Move']
                    san = board_before_move.san(chess.Move.from_uci(move_uci))
                    eval_cp = top_move.get('Centipawn')
                    eval_str = f"{eval_cp/100.0:.2f}" if eval_cp is not None else "N/A"
                    st.markdown(f"**{i+1}.** `{san}` (Eval: {eval_str})")
            else:
                st.subheader("Starting Position")
                st.info("Use the navigation buttons to step through the game.")
        
        # --- Use an expander for the full move list to save space ---
        with st.expander("Show Full Move List Analysis"):
            df_display = pd.DataFrame(analysis)
            st.dataframe(df_display[['move_number', 'color', 'move', 'best_move', 'eval_loss', 'move_quality']], use_container_width=True, hide_index=True)
            st.download_button("📥 Download Analysis (CSV)", df_display.to_csv(index=False), f"analysis_{info.get('White','N_A')}_vs_{info.get('Black','N_A')}.csv", "text/csv")