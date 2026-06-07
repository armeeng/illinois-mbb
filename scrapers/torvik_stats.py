import requests, pandas as pd, time
from pathlib import Path

GAMES   = Path(__file__).parent.parent / "data" / "games.csv"
PLAYERS = Path(__file__).parent.parent / "data" / "players.csv"
OUT     = Path(__file__).parent.parent / "data" / "stats.csv"

# Official column order from barttorvik.com/pstatheaders.xlsx
# pslice.php returns 66 columns (no hometown column that getadvstats has)
COLS = [
    "player_name", "team", "conf", "gp", "min_pct", "ortg", "usg", "efg", "ts",
    "orb", "drb", "ast", "tov", "ftm", "fta", "ft_pct",
    "two_pm", "two_pa", "two_p_pct", "tpm", "tpa", "tp_pct",
    "blk", "stl", "ftr", "yr", "ht", "num", "porpag", "adjoe", "pfr",
    "season_year", "pid", "type", "rec_rank", "ast_tov",
    "rim_made", "rim_att", "mid_made", "mid_att",
    "rim_pct", "mid_pct", "dunks_made", "dunks_att", "dunk_pct",
    "pick", "drtg", "adrtg", "dporpag", "stops",
    "bpm", "obpm", "dbpm", "gbpm", "mp",
    "ogbpm", "dgbpm", "oreb", "dreb", "treb", "ast_raw", "stl_raw", "blk_raw", "pts",
    "role", "three_p_100",
]


games   = pd.read_csv(GAMES, dtype=str)
players = pd.read_csv(PLAYERS, dtype=str).dropna(subset=["torvik_name"])
name_to_id = players.set_index("torvik_name")["espn_player_id"].to_dict()

existing     = pd.read_csv(OUT, dtype=str) if OUT.exists() else pd.DataFrame()
fetched_dates = set(existing["date"].unique()) if not existing.empty else set()
dates_to_fetch = sorted(set(games["game_date"].tolist()) - fetched_dates)

# One-time session setup: satisfies barttorvik's JS bot check
session = requests.Session()
session.headers.update({"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"})
session.post("https://barttorvik.com/", data={"js_test_submitted": "1"}, timeout=30)

rows = []
for dt in dates_to_fetch:
    print(dt)
    params = {"year": 2026, "start": "20251101", "end": dt.replace("-", ""), "top": 0, "csv": 1}
    df = None
    for attempt in range(1, 4):
        try:
            r = session.get("https://barttorvik.com/pslice.php", params=params, timeout=90)
            df = pd.read_csv(pd.io.common.StringIO(r.text), header=None, names=COLS)
            break
        except Exception as e:
            wait = attempt * 10
            print(f"  {dt}: attempt {attempt} failed ({e.__class__.__name__}), retrying in {wait}s…")
            time.sleep(wait)
    if df is None:
        print(f"  {dt}: skipped after 3 failed attempts")
        continue

    for _, row in df.iterrows():
        espn_id = name_to_id.get(str(row["player_name"]))
        if not espn_id:
            continue
        rec = {"espn_player_id": espn_id, "date": dt}
        for col in COLS:
            rec[col] = row[col]
        rows.append(rec)

    time.sleep(0.5)
    print(f"  {dt}: {len(df)} players fetched, {sum(1 for r in rows if r['date'] == dt)} matched")

new_df   = pd.DataFrame(rows)
combined = (
    pd.concat([existing, new_df])
    .drop_duplicates(["espn_player_id", "date"], keep="last")
    if not new_df.empty else existing
)
combined.to_csv(OUT, index=False)
print(f"Saved {len(combined)} stat rows → {OUT}")
