import streamlit as st
import pandas as pd
import duckdb
import joblib
from itertools import combinations
from pathlib import Path

COMBO_COLS = {
    "players":     "Players",
    "poss":        "Poss",
    "off_eff":     "Off Rtg",
    "def_eff":     "Def Rtg",
    "net_eff":     "Net Rtg",
}

ONOFF_COLS = {
    "player":      "Player",
    "on_poss":     "Poss (On)",
    "on_off_eff":  "ORtg (On)",
    "on_def_eff":  "DRtg (On)",
    "on_net_eff":  "Net (On)",
    "off_poss":    "Poss (Off)",
    "off_off_eff": "ORtg (Off)",
    "off_def_eff": "DRtg (Off)",
    "off_net_eff": "Net (Off)",
    "plus_minus":  "+/-",
}

DATA = Path(__file__).parent.parent / "data"
SQL_PATH = Path(__file__).parent.parent / "sql" / "lineup_stats.sql"
MODEL_PATH = Path(__file__).parent.parent / "modeling" / "models" / "lineup_model.joblib"

FEATURE_COLS = [
    "ht_delta", "yr_delta", "off_delta", "def_delta", "net_rating_delta",
    "reb_battle", "spacing_mismatch", "playmaking_delta", "interior_delta",
    "perimeter_defense_delta", "bpm_delta",
]

FAKE_GAME_ID = 999999999

def render_table(df):
    st.dataframe(df, width="stretch", hide_index=True, height=min(500, (len(df) + 1) * 35 + 3))


@st.cache_data
def load():
    gp = pd.read_csv(DATA / "grouped_possessions.csv", dtype={"game_id": str})
    games = pd.read_csv(DATA / "games.csv", dtype={"away_team_id": str, "home_team_id": str, "game_id": str})
    teams = pd.read_csv(DATA / "teams.csv", dtype={"team_id": str})
    players_full = pd.read_csv(DATA / "players.csv")[
        ["espn_player_id", "espn_name", "espn_team", "torvik_team"]
    ].drop_duplicates("espn_player_id")
    id_to_name = players_full.set_index("espn_player_id")["espn_name"].to_dict()

    # Teams with >= 2 games
    game_counts = pd.concat([
        games[["away_team_id"]].rename(columns={"away_team_id": "team_id"}),
        games[["home_team_id"]].rename(columns={"home_team_id": "team_id"}),
    ]).groupby("team_id").size().reset_index(name="game_count")
    qualified_ids = set(game_counts[game_counts["game_count"] >= 15]["team_id"])
    qualified_teams = teams[teams["team_id"].isin(qualified_ids)]

    # Map ESPN team name -> torvik abbreviation so Tab 2 can filter players
    espn_to_torvik = (
        players_full.dropna(subset=["espn_team", "torvik_team"])
        .drop_duplicates("espn_team")
        .set_index("espn_team")["torvik_team"]
        .to_dict()
    )
    qualified_torvik_teams = {
        espn_to_torvik[t] for t in qualified_teams["team_name"] if t in espn_to_torvik
    }

    return gp, games, qualified_teams, id_to_name, qualified_torvik_teams


@st.cache_data
def load_prediction_data():
    players = pd.read_csv(DATA / "players.csv")[["espn_player_id", "torvik_name"]].rename(
        columns={"torvik_name": "player_name"}
    )
    stats = pd.read_csv(DATA / "stats_git.csv").merge(players, on="espn_player_id", how="left")
    latest_date = stats["date"].max()
    latest_stats = stats[stats["date"] == latest_date].copy()
    latest_stats = latest_stats[latest_stats["player_name"].notna() & (latest_stats["player_name"].str.strip() != "")]
    latest_stats["display_name"] = (
        latest_stats["player_name"] + " (" + latest_stats["team"].fillna("") + ")"
    )
    return latest_stats, stats, latest_date


@st.cache_resource
def load_model():
    return joblib.load(MODEL_PATH)


def predict_from_sql(away_ids, home_ids, all_stats, latest_date):
    """
    Construct a fake one-row grouped_possessions + games, register alongside
    the real stats table, run the exact same SQL used for training, and return
    the feature row.
    """
    import datetime

    game_date = (
        pd.to_datetime(latest_date) + datetime.timedelta(days=1)
    ).strftime("%Y-%m-%d")

    fake_gp = pd.DataFrame([{
        "game_id":   FAKE_GAME_ID,
        "a1": away_ids[0], "a2": away_ids[1], "a3": away_ids[2],
        "a4": away_ids[3], "a5": away_ids[4],
        "h1": home_ids[0], "h2": home_ids[1], "h3": home_ids[2],
        "h4": home_ids[3], "h5": home_ids[4],
        "poss":     100,
        "away_pts": 0,
        "home_pts": 0,
        "net_pts":  0,
        "net_eff":  0.0,
        "lineup_id": 1,
    }])

    fake_games = pd.DataFrame([{
        "game_id":   FAKE_GAME_ID,
        "game_date": game_date,
    }])

    sql = SQL_PATH.read_text()

    conn = duckdb.connect()
    conn.register("grouped_possessions", fake_gp)
    conn.register("games", fake_games)
    conn.register("stats", all_stats)

    result = conn.execute(sql).df()
    conn.close()

    return result


def filter_team(gp, games, tid):
    team_games = games[(games["away_team_id"] == tid) | (games["home_team_id"] == tid)]
    df = gp[gp["game_id"].isin(team_games["game_id"])].merge(
        team_games[["game_id", "away_team_id"]], on="game_id"
    )
    df["is_away"] = df["away_team_id"] == tid
    df["team_players"] = df.apply(
        lambda r: [r[f"a{i}"] for i in range(1, 6)] if r["is_away"]
                  else [r[f"h{i}"] for i in range(1, 6)], axis=1
    )
    df["pts_for"]     = df.apply(lambda r: r["away_pts"] if r["is_away"] else r["home_pts"], axis=1)
    df["pts_against"] = df.apply(lambda r: r["home_pts"] if r["is_away"] else r["away_pts"], axis=1)
    return df


def combo_stats(df, n, id_to_name, min_poss):
    rows = []
    for _, row in df.iterrows():
        for combo in combinations(sorted(row["team_players"]), n):
            rows.append({"combo": combo, "poss": row["poss"],
                         "pts_for": row["pts_for"], "pts_against": row["pts_against"]})
    if not rows:
        return pd.DataFrame()
    agg = pd.DataFrame(rows).groupby("combo").agg(
        poss=("poss", "sum"),
        pts_for=("pts_for", "sum"),
        pts_against=("pts_against", "sum")
    ).reset_index()
    agg = agg[agg["poss"] >= min_poss]
    agg["off_eff"] = agg["pts_for"]     / agg["poss"] * 100
    agg["def_eff"] = agg["pts_against"] / agg["poss"] * 100
    agg["net_eff"] = agg["off_eff"] - agg["def_eff"]
    agg["players"] = agg["combo"].apply(
        lambda c: " / ".join(id_to_name.get(p, str(p)) for p in c)
    )
    return agg[["players", "poss", "off_eff", "def_eff", "net_eff"]].sort_values("net_eff", ascending=False)


def on_off_stats(df, id_to_name):
    all_players = {p for row in df["team_players"] for p in row}
    rows = []
    for pid in all_players:
        on  = df[df["team_players"].apply(lambda lst: pid in lst)]
        off = df[df["team_players"].apply(lambda lst: pid not in lst)]

        def eff(d):
            p = d["poss"].sum()
            if p == 0:
                return None, None, None
            o = d["pts_for"].sum() / p * 100
            de = d["pts_against"].sum() / p * 100
            return o, de, o - de

        on_o, on_d, net_on   = eff(on)
        off_o, off_d, net_off = eff(off)
        rows.append({
            "player":       id_to_name.get(pid, str(pid)),
            "on_poss":      on["poss"].sum(),
            "on_off_eff":   on_o,
            "on_def_eff":   on_d,
            "on_net_eff":   net_on,
            "off_poss":     off["poss"].sum(),
            "off_off_eff":  off_o,
            "off_def_eff":  off_d,
            "off_net_eff":  net_off,
            "plus_minus":   (net_on - net_off) if (net_on is not None and net_off is not None) else None,
        })
    out = pd.DataFrame(rows)
    if out.empty or "plus_minus" not in out.columns:
        return out
    return out.sort_values("plus_minus", ascending=False)


# ── App ──────────────────────────────────────────────────────────────────────

st.set_page_config(page_title="Lineup Analytics", layout="wide")

st.markdown("""
<style>
#MainMenu, footer, header {visibility: hidden;}
.block-container {padding-top: 2rem; padding-bottom: 2rem; max-width: 1100px;}
h1 {font-size: 1.5rem; font-weight: 600; margin-bottom: 0;}
h3 {font-size: 1rem; font-weight: 600; margin-top: 1.5rem; margin-bottom: 0.25rem;}
</style>
""", unsafe_allow_html=True)

st.title("Lineup Analytics")

tab1, tab2 = st.tabs(["Lineup Analytics", "Lineup Predictor"])

# ── Tab 1: existing analytics ─────────────────────────────────────────────────
with tab1:
    gp, games, teams, id_to_name, qualified_torvik_teams = load()

    col1, col2 = st.columns([2, 1], vertical_alignment="center")
    with col1:
        team_name = st.selectbox("Team", sorted(teams["team_name"].unique()), label_visibility="collapsed")
    with col2:
        min_poss = st.slider("Min possessions", 0, 500, 30)

    tid = teams[teams["team_name"] == team_name]["team_id"].iloc[0]
    df = filter_team(gp, games, tid)

    if df.empty:
        st.warning("No data found for this team.")
        st.stop()

    st.caption(f"{len(df)} lineup stints · {int(df['poss'].sum())} total possessions")
    st.divider()

    for n, label in [(5, "5-Man"), (4, "4-Man"), (3, "3-Man"), (2, "2-Man")]:
        st.subheader(f"{label} Lineups")
        out = combo_stats(df, n, id_to_name, min_poss)
        if out.empty:
            st.caption(f"No {label.lower()} lineups with ≥{min_poss} possessions.")
        else:
            render_table(out.reset_index(drop=True).round(1).rename(columns=COMBO_COLS))

    st.subheader("Player On/Off")
    onoff = on_off_stats(df, id_to_name)
    if onoff.empty:
        st.caption("No on/off data available.")
    else:
        render_table(onoff.reset_index(drop=True).round(1).rename(columns=ONOFF_COLS))

# ── Tab 2: lineup predictor ───────────────────────────────────────────────────
with tab2:
    latest_stats, all_stats, latest_date = load_prediction_data()
    model = load_model()
    _, _, _, _, qualified_torvik_teams = load()

    st.caption(f"Using player stats from **{latest_date}** (latest available)")

    all_display = sorted(
        latest_stats[latest_stats["team"].isin(qualified_torvik_teams)]["display_name"].dropna().unique()
    )

    col_away, col_home = st.columns(2)

    with col_away:
        st.subheader("Away Lineup")
        away_selections = []
        for i in range(1, 6):
            sel = st.selectbox(f"Away Player {i}", ["— select —"] + all_display, key=f"away_{i}")
            away_selections.append(sel)

    with col_home:
        st.subheader("Home Lineup")
        home_selections = []
        for i in range(1, 6):
            sel = st.selectbox(f"Home Player {i}", ["— select —"] + all_display, key=f"home_{i}")
            home_selections.append(sel)

    if st.button("Predict Net Efficiency", type="primary"):
        away_missing = [s for s in away_selections if s == "— select —"]
        home_missing = [s for s in home_selections if s == "— select —"]

        if away_missing or home_missing:
            st.error("Please select all 10 players before predicting.")
        else:
            def resolve_ids(selections):
                ids = []
                for sel in selections:
                    name = sel.rsplit(" (", 1)[0]
                    match = latest_stats[latest_stats["player_name"] == name]
                    if match.empty:
                        st.error(f"Could not find stats for '{name}' at {latest_date}.")
                        return None
                    ids.append(int(match.iloc[0]["espn_player_id"]))
                return ids

            away_ids = resolve_ids(away_selections)
            home_ids = resolve_ids(home_selections)

            if away_ids is not None and home_ids is not None:
                with st.spinner("Running SQL feature pipeline…"):
                    result = predict_from_sql(away_ids, home_ids, all_stats, latest_date)

                if result.empty or result[FEATURE_COLS].isnull().all(axis=None):
                    st.error(
                        "Could not compute features — one or more players may be missing "
                        f"stats at {latest_date}. Check that all selected players appear in "
                        "the stats table for that date."
                    )
                else:
                    features = result[FEATURE_COLS].iloc[[0]]
                    prediction = model.predict(features)[0]

                    st.divider()
                    direction = "Away" if prediction > 0 else "Home"
                    color = "#1f77b4" if prediction > 0 else "#d62728"
                    st.markdown(
                        f"<h2 style='text-align:center; color:{color};'>"
                        f"Predicted Net Efficiency: {prediction:+.2f} ({direction} favored)"
                        f"</h2>",
                        unsafe_allow_html=True,
                    )
                    st.caption("Positive = away advantage · Negative = home advantage")

                    STAT_COLS = ["player_name", "team", "ortg", "drtg", "usg", "ts", "bpm", "ht", "yr"]
                    STAT_LABELS = ["Player", "Team", "ORtg", "DRtg", "USG%", "TS%", "BPM", "Height", "Yr"]

                    def build_player_table(selections):
                        names = [s.rsplit(" (", 1)[0] for s in selections]
                        rows = latest_stats[latest_stats["player_name"].isin(names)].drop_duplicates("player_name")
                        rows = rows.set_index("player_name").loc[names].reset_index()
                        return rows[STAT_COLS].rename(columns=dict(zip(STAT_COLS, STAT_LABELS)))

                    st.subheader("Away Lineup")
                    render_table(build_player_table(away_selections))

                    st.subheader("Home Lineup")
                    render_table(build_player_table(home_selections))
