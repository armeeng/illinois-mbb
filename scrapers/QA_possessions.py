import requests, pandas as pd, time
from pathlib import Path

DATA = Path(__file__).parent.parent / "data"
ESPN = "https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/summary"


def fetch(game_id):
    return requests.get(ESPN, params={"event": game_id}, timeout=15).json()


def box_poss(d):
    """Sum FGA + 0.44*FTA + TO - ORB across both teams from box score totals."""
    total = 0
    for team in d["boxscore"]["players"]:
        stats = team["statistics"][0]
        kv = dict(zip(stats.get("keys", stats.get("names", [])), stats.get("totals", [])))
        fg = kv.get("fieldGoalsMade-fieldGoalsAttempted", "0-0")
        fga = int(fg.split("-")[1]) if "-" in fg else 0
        ft = kv.get("freeThrowsMade-freeThrowsAttempted", "0-0")
        fta = int(ft.split("-")[1]) if "-" in ft else 0
        to_ = int(kv.get("turnovers", 0) or 0)
        orb = int(kv.get("offensiveRebounds", 0) or 0)
        total += fga + 0.44 * fta + to_ - orb
    return total


def check_game(stints, d):
    errors = []

    # 1. more than one stint
    if len(stints) <= 1:
        errors.append(f"only {len(stints)} stint(s)")

    # 2. total possessions vs box score
    bp = box_poss(d)
    sp = stints["poss"].sum()
    if abs(sp - bp) > 0.5:
        errors.append(f"poss mismatch: stints={sp:.1f}, box={bp:.1f} (delta={sp - bp:+.1f})")

    # 3. net points vs final score differential
    plays = d.get("plays", [])
    if plays:
        expected = int(plays[-1]["awayScore"]) - int(plays[-1]["homeScore"])
        actual = int(stints["net_pts"].sum())
        if actual != expected:
            errors.append(f"net_pts mismatch: stints={actual}, final_diff={expected}")

    return errors


def main():
    poss = pd.read_csv(DATA / "raw_possessions.csv", dtype={"game_id": str})
    game_ids = poss["game_id"].unique()

    pass_ct = fail_ct = skip_ct = 0
    passed_ids = set()
    for gid in game_ids:
        stints = poss[poss["game_id"] == gid]
        try:
            d = fetch(gid)
        except Exception as e:
            print(f"SKIP  {gid}: {e}")
            skip_ct += 1
            continue

        errors = check_game(stints, d)
        if errors:
            fail_ct += 1
            print(f"FAIL  {gid} ({len(stints)} stints): {'; '.join(errors)}")
        else:
            pass_ct += 1
            passed_ids.add(gid)
            print(f"PASS  {gid} ({len(stints)} stints)")

        time.sleep(0.1)

    print(f"\n{pass_ct} passed, {fail_ct} failed, {skip_ct} skipped  ({len(game_ids)} total)")

    away_cols = [f"a{i}" for i in range(1, 6)]
    home_cols = [f"h{i}" for i in range(1, 6)]
    player_cols = away_cols + home_cols
    passed = poss[poss["game_id"].isin(passed_ids)].copy()
    for cols in (away_cols, home_cols):
        passed[cols] = passed[cols].apply(
            lambda r: pd.Series(sorted((v for v in r if pd.notna(v))) + [None] * r.isna().sum(), index=cols), axis=1
        )
    g = passed.groupby(["game_id"] + player_cols, as_index=False).agg(
        poss=("poss", "sum"),
        away_pts=("away_pts", "sum"),
        home_pts=("home_pts", "sum"),
        net_pts=("net_pts", "sum"))
    g["net_eff"] = (g["net_pts"] / g["poss"]) * 100
    g["lineup_id"] = g.groupby("game_id").cumcount() + 1
    g.to_csv(DATA / "grouped_possessions.csv", index=False)
    print(f"Wrote grouped_possessions.csv ({len(g)} lineups across {len(passed_ids)} games)")



if __name__ == "__main__":
    main()
