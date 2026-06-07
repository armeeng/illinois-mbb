import requests, pandas as pd, io
from collections import defaultdict
from rapidfuzz import process, fuzz
from pathlib import Path

PLAYERS          = Path(__file__).parent.parent / "data" / "players.csv"
AMBIGUOUS        = Path(__file__).parent.parent / "data" / "ambiguous_players.txt"
UNMATCHED_TORVIK = Path(__file__).parent.parent / "data" / "unmatched_torvik.txt"
UNMATCHED_ESPN   = Path(__file__).parent.parent / "data" / "unmatched_espn.txt"
NAME_INITIAL_CUTOFF = 70   # wide net for initial name candidates
COMPOSITE_CUTOFF     = 72  # minimum composite score to call it a match
AMBIGUOUS_DELTA      = 3   # flag ambiguous when top two scores are this close

r = requests.get("https://barttorvik.com/getadvstats.php", params={"year": 2026, "csv": 1}, timeout=30)
# getadvstats has 67 cols (pslice + hometown at col 33):
#   0=name, 1=team, 25=yr, 26=height, 31=season_year, 32=pid
raw = pd.read_csv(io.StringIO(r.text), header=None)
torvik_players = raw[[0, 1, 26, 31]].rename(columns={0: "name", 1: "team", 26: "height", 31: "season_year"})
torvik_players["name"] = torvik_players["name"].astype(str)

torvik_name_list = list(dict.fromkeys(torvik_players["name"].tolist()))  # unique, order-preserving

name_to_rows = defaultdict(list)
for _, row in torvik_players.iterrows():
    name_to_rows[row["name"]].append(row)

espn_df = pd.read_csv(PLAYERS, dtype=str)
has_height = "espn_height" in espn_df.columns
has_team = "espn_team" in espn_df.columns
ambiguous = []

NO_MATCH = {"torvik_name": None, "torvik_height": None, "torvik_team": None}


def normalize_height(h):
    if pd.isna(h) or not h or str(h).strip() == "nan":
        return None
    s = str(h).strip()
    return s if "-" in s else None


def row_score(torvik_row, name_score, espn_height, espn_team):
    """Composite score combining name (75%), team (12.5%), and height (12.5%)."""
    team_sc   = fuzz.token_set_ratio(espn_team, torvik_row["team"]) if espn_team else 50
    height_sc = 100 if (espn_height and normalize_height(torvik_row["height"]) == espn_height) else 0
    return 0.75 * name_score + 0.125 * team_sc + 0.125 * height_sc


def best_match(row):
    name       = row["espn_name"]
    espn_height = normalize_height(row["espn_height"]) if has_height else None
    espn_team   = row["espn_team"] if has_team else None

    name_candidates = process.extract(name, torvik_name_list, score_cutoff=NAME_INITIAL_CUTOFF)
    if not name_candidates:
        return NO_MATCH

    scored = []
    for cand_name, name_sc, _ in name_candidates:
        for torvik_row in name_to_rows[cand_name]:
            scored.append((row_score(torvik_row, name_sc, espn_height, espn_team), torvik_row))

    scored.sort(key=lambda x: x[0], reverse=True)
    best_sc, best_row = scored[0]

    if best_sc < COMPOSITE_CUTOFF:
        return NO_MATCH

    if len(scored) > 1 and (best_sc - scored[1][0]) < AMBIGUOUS_DELTA:
        ambiguous.append(
            f"{name}: {best_row['name']} ({best_sc:.1f}) vs "
            f"{scored[1][1]['name']} ({scored[1][0]:.1f})"
        )

    return {
        "torvik_name":   best_row["name"],
        "torvik_height": best_row["height"] if not pd.isna(best_row["height"]) else None,
        "torvik_team":   best_row["team"],
    }


results = espn_df.apply(best_match, axis=1, result_type="expand")
espn_df[["torvik_name", "torvik_height", "torvik_team"]] = results
espn_df.to_csv(PLAYERS, index=False)

if ambiguous:
    AMBIGUOUS.write_text("\n".join(ambiguous))
    print(f"Wrote {len(ambiguous)} ambiguous mappings → {AMBIGUOUS}")

matched_torvik = set(espn_df["torvik_name"].dropna().tolist())

unmatched_torvik = sorted(n for n in torvik_name_list if n not in matched_torvik)
if unmatched_torvik:
    UNMATCHED_TORVIK.write_text("\n".join(unmatched_torvik))
    print(f"Wrote {len(unmatched_torvik)} unmatched Torvik names → {UNMATCHED_TORVIK}")

unmatched_espn = espn_df[espn_df["torvik_name"].isna()][["espn_player_id", "espn_name"]]
if not unmatched_espn.empty:
    lines = [f"{row.espn_player_id}\t{row.espn_name}" for row in unmatched_espn.itertuples()]
    UNMATCHED_ESPN.write_text("\n".join(lines))
    print(f"Wrote {len(lines)} unmatched ESPN players → {UNMATCHED_ESPN}")

print(f"Matched {espn_df['torvik_name'].notna().sum()} / {len(espn_df)} players")
