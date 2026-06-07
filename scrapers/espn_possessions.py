import requests, pandas as pd, time
from pathlib import Path

DATA = Path(__file__).parent.parent / "data"


def stints(game_id):
    d = requests.get(
        "https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/summary",
        params={"event": game_id}, timeout=15
    ).json()

    competitors = {c["homeAway"]: c["team"]["id"] for c in d["header"]["competitions"][0]["competitors"]}
    actual_away_tid = competitors["away"]
    actual_home_tid = competitors["home"]
    on = {s["team"]["id"]: {p["athlete"]["id"] for p in s["statistics"][0]["athletes"] if p.get("starter")}
          for s in d["boxscore"]["players"]}

    rows, sid, sa, sh, fga, fta, to_, orb = [], 0, 0, 0, 0, 0, 0, 0

    def flush(ea, eh):
        nonlocal sid
        poss = fga + 0.44 * fta + to_ - orb
        a = (sorted(on.get(actual_away_tid, []))[:5] + [None] * 5)[:5]
        h = (sorted(on.get(actual_home_tid, []))[:5] + [None] * 5)[:5]
        net_pts = (ea - sa) - (eh - sh)
        net_eff = round(net_pts / poss * 100, 1) if poss > 0 else None
        away_pts = ea - sa
        home_pts = eh - sh
        rows.append([game_id, sid] + a + h + [poss, away_pts, home_pts, net_pts, net_eff])
        sid += 1

    plays, i = d["plays"], 0
    while i < len(plays):
        p, typ = plays[i], plays[i]["type"].get("text", "")
        ea, eh = int(p["awayScore"]), int(p["homeScore"])
        if "Substitution" in typ:
            flush(ea, eh)
            sa, sh, fga, fta, to_, orb = ea, eh, 0, 0, 0, 0
            period, clock = p["period"]["number"], p["clock"]["displayValue"]
            while i < len(plays) and "Substitution" in plays[i]["type"].get("text", "") \
                    and plays[i]["period"]["number"] == period and plays[i]["clock"]["displayValue"] == clock:
                if plays[i].get("participants"):
                    pid = plays[i]["participants"][0]["athlete"]["id"]
                    tid = plays[i]["team"]["id"]
                    if "subbing out" in plays[i].get("text", ""):
                        on.get(tid, set()).discard(pid)
                    else:
                        on.get(tid, set()).add(pid)
                i += 1
        else:
            fga += bool(p.get("shootingPlay")) and typ != "MadeFreeThrow"
            fta += typ == "MadeFreeThrow"
            to_ += "Turnover" in typ
            orb += "Offensive Rebound" in typ
            i += 1

    if plays:
        flush(int(plays[-1]["awayScore"]), int(plays[-1]["homeScore"]))
    return rows


games = pd.read_csv(DATA / "games.csv", dtype=str)
all_rows = []
for g in games.itertuples(index=False):
    try:
        all_rows.extend(stints(g.game_id))
    except Exception as e:
        print(f"skip {g.game_id}: {e}")
    time.sleep(0.1)

cols = ["game_id", "stint_id", "a1", "a2", "a3", "a4", "a5", "h1", "h2", "h3", "h4", "h5", "poss", "away_pts", "home_pts", "net_pts", "net_eff"]
pd.DataFrame(all_rows, columns=cols).to_csv(DATA / "raw_possessions.csv", index=False)
print(f"Saved {len(all_rows)} stints")
