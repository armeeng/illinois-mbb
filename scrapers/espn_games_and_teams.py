import requests, pandas as pd, time
from datetime import date, timedelta
from pathlib import Path

DATA = Path(__file__).parent.parent / "data"
DATA.mkdir(parents=True, exist_ok=True)
URL = "https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/scoreboard"

games_out = DATA / "games.csv"
teams_out = DATA / "teams.csv"

existing_games = pd.read_csv(games_out, dtype=str) if games_out.exists() else pd.DataFrame(columns=["game_id", "game_date", "away_team_id", "home_team_id"])
existing_teams = pd.read_csv(teams_out, dtype=str) if teams_out.exists() else pd.DataFrame(columns=["team_id", "team_name"])

fetched_dates = set(existing_games["game_date"].unique()) if not existing_games.empty else set()
seen_ids = set(existing_teams["team_id"].tolist())

game_rows, team_rows = [], []
d = date(2025, 11, 1)
while d <= date(2026, 4, 15):
    dstr = d.strftime("%Y%m%d")
    if dstr not in fetched_dates:
        r = requests.get(URL, params={"dates": dstr, "limit": 200, "groups": 50}, timeout=15).json()
        for ev in r.get("events", []):
            comp = ev["competitions"][0]
            sides = {c["homeAway"]: c["team"]["id"] for c in comp["competitors"]}
            game_rows.append({"game_id": ev["id"], "game_date": ev["date"][:10],
                              "away_team_id": sides.get("away"), "home_team_id": sides.get("home")})
            for c in comp["competitors"]:
                team = c["team"]
                if team["id"] not in seen_ids:
                    team_rows.append({"team_id": team["id"], "team_name": team["displayName"]})
                    seen_ids.add(team["id"])
        time.sleep(0.2)
    d += timedelta(days=1)

pd.concat([existing_games, pd.DataFrame(game_rows)]).drop_duplicates("game_id", keep="last").to_csv(games_out, index=False)
pd.concat([existing_teams, pd.DataFrame(team_rows)]).drop_duplicates("team_id", keep="last").to_csv(teams_out, index=False)
print(f"Saved {len(existing_games) + len(game_rows)} games, {len(seen_ids)} teams")
