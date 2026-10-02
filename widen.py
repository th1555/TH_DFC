#!/usr/bin/env python3
"""
widen.py  —  add whole leagues to the data, without losing what you have
========================================================================
One command per batch of leagues:

    python widen.py 124 123          # e.g. Scottish League One + Championship

For each league it finds every team, pulls every squad, and fetches each
player's full season history from FotMob, ADDING the results to the master file
fotmob_player_seasons.csv (it never overwrites earlier leagues).

Safe to stop and restart: progress is saved every 25 players, and on a rerun any
player already in the master file is skipped. To force a fresh pull of players
you already have (e.g. a mid-season refresh), add --refresh.

Run at home (FotMob blocks cloud servers). Allow ~3 seconds per player.
Afterwards:  python league_info.py  then rebuild as usual.

Deps: requests, beautifulsoup4, lxml, pandas
(+ fotmob_league.py, fotmob_squad.py, ingest_fotmob.py beside it)
"""
from __future__ import annotations
import os
import sys
import time
import pandas as pd
import fotmob_league as fl
import fotmob_squad as fs
import ingest_fotmob as ing

MASTER = "fotmob_player_seasons.csv"
DELAY = 3.0
SAVE_EVERY = 25
KEY = ["player_id", "season", "league_id", "tournament_id"]


def load_master():
    return pd.read_csv(MASTER) if os.path.exists(MASTER) else pd.DataFrame()


def merge_save(master, new_rows):
    """Add new rows to the master file; a re-pulled player replaces his old rows."""
    if not new_rows:
        return master
    new = pd.DataFrame(new_rows)
    if len(master):
        fresh = set(new.player_id.astype(int))
        master = master[~master.player_id.astype(int).isin(fresh)]
        master = pd.concat([master, new], ignore_index=True)
    else:
        master = new
    master = master.drop_duplicates(subset=[k for k in KEY if k in master.columns], keep="last")
    tmp = MASTER + ".tmp"
    master.to_csv(tmp, index=False)
    os.replace(tmp, MASTER)                 # never leaves a half-written master
    return master


def collect_players(league_ids):
    """Every (player_id, name, position, team) in the given leagues' squads."""
    squads = []
    for lid in league_ids:
        teams = fl.teams_of(lid)
        time.sleep(DELAY)
        if teams.empty:
            print(f"  !! league {lid}: no teams found, skipping (paste the output above)")
            continue
        for tid in teams.team_id.astype(int):
            try:
                sq = fs.squad_of(tid)
                if len(sq):
                    sq["league_id"] = lid
                    squads.append(sq)
            except Exception as e:
                print(f"  team {tid}: error {e}")
            time.sleep(DELAY)
    if not squads:
        return pd.DataFrame()
    allp = pd.concat(squads, ignore_index=True).drop_duplicates("player_id")
    return allp


def main(args):
    refresh = "--refresh" in args
    league_ids = [int(a) for a in args if a.lstrip("-").isdigit()]
    if not league_ids:
        raise SystemExit("Give one or more FotMob league ids, e.g.  python widen.py 124 123")

    master = load_master()
    have = set(master.player_id.astype(int)) if len(master) else set()
    print(f"master file: {len(master)} rows, {len(have)} players already held\n")

    print(f"Step 1: finding squads for league(s) {league_ids}")
    squads = collect_players(league_ids)
    if squads.empty:
        raise SystemExit("No players found.")
    todo = [int(p) for p in squads.player_id if refresh or int(p) not in have]
    skip = sum(int(p) in have for p in squads.player_id)
    print(f"\n{len(squads)} players in these squads; {skip} already held"
          f"{' (re-pulling anyway)' if refresh else ', skipped'}; {len(todo)} to fetch"
          f" (~{len(todo)*DELAY/60:.0f} min)\n")

    print("Step 2: fetching season histories")
    buffer, done, errors = [], 0, 0
    try:
        for i, pid in enumerate(todo, 1):
            try:
                buffer += ing.parse_player(ing.fetch_player(pid))
                done += 1
            except Exception as e:
                errors += 1
                print(f"  ERR {pid}: {e}")
            if i % SAVE_EVERY == 0:
                master = merge_save(master, buffer); buffer = []
                print(f"  {i}/{len(todo)} fetched, saved")
            time.sleep(DELAY)
    except KeyboardInterrupt:
        print("\nStopped by you. Saving what was fetched; rerun the same command to resume.")
    master = merge_save(master, buffer)
    print(f"\nDone: {done} players fetched, {errors} errors. Master file now "
          f"{len(master)} rows, {master.player_id.nunique()} players.")
    print("Next:  python league_info.py   then rebuild "
          "(store_pipeline, match_market, export_site).")


if __name__ == "__main__":
    main(sys.argv[1:])
