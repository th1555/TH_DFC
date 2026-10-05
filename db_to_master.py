#!/usr/bin/env python3
"""
db_to_master.py  —  recreate fotmob_player_seasons.csv from dumbarton.db
=======================================================================
Use on a device that has the repo (and therefore dumbarton.db) but not the
master season file. Writes the same columns widen.py and store_pipeline.py use.

    python db_to_master.py

Refuses to overwrite an existing master file unless you add --force.
"""
import os
import sqlite3
import sys
import pandas as pd

MASTER = "fotmob_player_seasons.csv"


def main(force=False):
    if os.path.exists(MASTER) and not force:
        raise SystemExit(f"{MASTER} already exists, so nothing to recover. "
                         "Add --force only if you are sure it is out of date.")
    if not os.path.exists("dumbarton.db"):
        raise SystemExit("No dumbarton.db here. Run this inside the repo folder.")
    conn = sqlite3.connect("dumbarton.db")
    cols = {r[1] for r in conn.execute("PRAGMA table_info(players)")}
    age = "p.age" if "age" in cols else "NULL"
    dob = "p.dob" if "dob" in cols else "NULL"
    nat = "p.nationality" if "nationality" in cols else "NULL"
    df = pd.read_sql(
        f"SELECT s.player_id, p.name AS player_name, p.position, {age} AS age, {dob} AS dob, {nat} AS nationality, "
        "s.season, s.league_name AS league, s.league_id, s.tournament_id, s.team, "
        "s.appearances, s.goals, s.assists, s.goal_contribs, s.minutes, s.per_app, "
        "s.is_cup, s.transfer_type FROM player_season_stats s "
        "LEFT JOIN players p USING(player_id)", conn)
    conn.close()
    df["is_cup"] = df.is_cup.fillna(0).astype(int).astype(bool)
    df["per90"] = None
    df.to_csv(MASTER, index=False)
    import db
    league_rows = df[~df.is_cup & ~df.league.apply(db.is_not_league)]
    by_league = league_rows.groupby("league_id").player_id.nunique().sort_values(ascending=False)
    print(f"wrote {MASTER}: {len(df)} rows, {df.player_id.nunique()} players")
    print("players per league id (top 12):")
    print(by_league.head(12).to_string())


if __name__ == "__main__":
    main("--force" in sys.argv)
