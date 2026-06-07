import requests, pandas as pd, time
from pathlib import Path

SEASON = 2026
DATA = Path(__file__).parent.parent / "data"
OUT = DATA / "players.csv"

teams_df = pd.read_csv(DATA / "teams.csv", dtype=str)
team_id_to_name = dict(zip(teams_df["team_id"], teams_df["team_name"]))
team_ids = teams_df["team_id"].tolist()

COLS = [
    "espn_player_id", "season", "espn_name", "espn_height", "espn_weight", "espn_team",
    "torvik_name", "torvik_height", "torvik_team",
]
existing = pd.read_csv(OUT, dtype=str) if OUT.exists() else pd.DataFrame(columns=COLS)
for col in COLS:
    if col not in existing.columns:
        existing[col] = None

seen = set(existing["espn_player_id"].tolist())
rows = []
for tid in team_ids:
    team_name = team_id_to_name.get(tid, "")
    for a in requests.get(f"https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/teams/{tid}/roster", timeout=15).json().get("athletes", []):
        if a["id"] not in seen:
            ht_in = a.get("height")
            ht = f"{int(ht_in) // 12}-{int(ht_in) % 12}" if ht_in else None
            wt = int(a["weight"]) if a.get("weight") else None
            rows.append({
                "espn_player_id": a["id"],
                "season": SEASON,
                "espn_name": a["displayName"],
                "espn_height": ht,
                "espn_weight": wt,
                "espn_team": team_name,
                "torvik_name": None,
                "torvik_height": None,
                "torvik_team": None,
            })
            seen.add(a["id"])
    time.sleep(0.1)

pd.concat([existing, pd.DataFrame(rows)])[COLS].drop_duplicates("espn_player_id").to_csv(OUT, index=False)
print(f"Saved {len(existing) + len(rows)} players")
