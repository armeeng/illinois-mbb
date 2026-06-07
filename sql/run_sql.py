import duckdb
import pandas as pd
from pathlib import Path

DATA = Path(__file__).parent.parent / "data"

conn = duckdb.connect()
conn.register("grouped_possessions", pd.read_csv(DATA / "grouped_possessions.csv"))
conn.register("games", pd.read_csv(DATA / "games.csv"))

players = pd.read_csv(DATA / "players.csv")[["espn_player_id", "torvik_name"]].rename(columns={"torvik_name": "player_name"})
stats = pd.read_csv(DATA / "stats.csv").merge(players, on="espn_player_id", how="left")
conn.register("stats", stats)

sql = (Path(__file__).parent / "lineup_stats.sql").read_text()
result = conn.execute(sql).df().dropna()
result.to_csv(DATA / "lineup_stats.csv", index=False)
print(f"Wrote {len(result)} rows to {DATA / 'lineup_stats.csv'}")