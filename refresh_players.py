#!/usr/bin/env python3
"""
refresh_players.py  —  re-pull players you already have, to add nationality
===========================================================================
Players pulled before nationality was captured have it blank. This re-fetches
them from FotMob and replaces their rows in fotmob_player_seasons.csv, which
also brings their season histories up to date.

    python refresh_players.py --probe 5   # try 5 players first and show what it finds
    python refresh_players.py             # everyone still missing a nationality
    python refresh_players.py --all       # re-pull every player (full refresh)

Safe to stop (Ctrl+C) and rerun: progress is saved every 25 players, and players
who already have a nationality are skipped. Allow ~3 seconds per player.
Run at home (FotMob blocks cloud servers).
"""
import json
import sys
import time
import pandas as pd
import ingest_fotmob as ing
import widen

DELAY = 3.0
SAVE_EVERY = 25


def probe(n):
    master = widen.load_master()
    ids = list(dict.fromkeys(master.player_id.astype(int)))[:n]
    for pid in ids:
        data = ing.fetch_player(pid)
        nat = ing._nationality_from(data)
        print(f"  {pid:>8}  {data.get('name','?'):<28} nationality: {nat or '(not found)'}")
        if nat is None:
            info = data.get("playerInformation")
            print("    [check] playerInformation:", json.dumps(info, ensure_ascii=False)[:700])
            print("    [check] top-level keys:", list(data.keys())[:30])
            print("    >> paste these [check] lines back")
        time.sleep(DELAY)


def main(args):
    if "--probe" in args:
        i = args.index("--probe")
        return probe(int(args[i + 1]) if len(args) > i + 1 else 5)
    master = widen.load_master()
    if master.empty:
        raise SystemExit("No fotmob_player_seasons.csv here.")
    ids = list(dict.fromkeys(master.player_id.astype(int)))
    if "--all" not in args and "nationality" in master.columns:
        has = set(master.loc[master.nationality.notna(), "player_id"].astype(int))
        ids = [p for p in ids if p not in has]
    print(f"{len(ids)} players to re-pull (~{len(ids)*DELAY/60:.0f} min). Ctrl+C to pause.\n")

    buffer, done, found, errors = [], 0, 0, 0
    try:
        for i, pid in enumerate(ids, 1):
            try:
                rows = ing.parse_player(ing.fetch_player(pid))
                if rows:
                    buffer += rows
                    found += int(rows[0].get("nationality") is not None)
                done += 1
            except Exception as e:
                errors += 1
                print(f"  ERR {pid}: {e}")
            if i % SAVE_EVERY == 0:
                master = widen.merge_save(master, buffer); buffer = []
                print(f"  {i}/{len(ids)} done, saved ({found} with a nationality so far)")
            time.sleep(DELAY)
    except KeyboardInterrupt:
        print("\nPaused. Saving progress; rerun the same command to continue.")
    master = widen.merge_save(master, buffer)
    print(f"\nRe-pulled {done} players ({found} with a nationality), {errors} errors.")
    print("Next: rebuild (store_pipeline, match_market, export_site).")


if __name__ == "__main__":
    main(sys.argv[1:])
