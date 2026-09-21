#!/usr/bin/env python3
"""
FotMob league puller  —  Dumbarton SL2 recruitment engine (division layer)
==========================================================================
Given a FotMob LEAGUE id, return every team in it (team_id, name), so you can
feed the whole division into fotmob_squad.py without hand-collecting team ids.
Confirmed league ids so far: 125 = Scottish League Two, 123 = Championship.
Find others from the FotMob URL: fotmob.com/leagues/{ID}/...

Diagnostic-first: the league-page JSON structure hasn't been eyeballed yet, so if
the auto-extract misses, this prints the shape so we can lock the parser in one
pass. Paste that back if so.

Usage:
  python fotmob_league.py 125            # Scottish League Two
  python fotmob_league.py 125 124 123    # several divisions at once

Deps: requests, beautifulsoup4, lxml, pandas
"""
from __future__ import annotations
import sys
import json
import time
import requests
import pandas as pd
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/124.0 Safari/537.36"),
    "Accept-Language": "en-US,en;q=0.9",
}
DELAY = 3.0


def find_key(obj, key):
    if isinstance(obj, dict):
        if key in obj:
            return obj[key]
        for v in obj.values():
            r = find_key(v, key)
            if r is not None:
                return r
    elif isinstance(obj, list):
        for v in obj:
            r = find_key(v, key)
            if r is not None:
                return r
    return None


def collect_teams(obj, acc, seen):
    """Gather dicts that look like teams (int id + str name) within a subtree."""
    if isinstance(obj, dict):
        tid, nm = obj.get("id"), obj.get("name")
        if isinstance(tid, int) and isinstance(nm, str) and nm and tid not in seen:
            seen.add(tid)
            acc.append({"team_id": tid, "name": nm})
        for v in obj.values():
            collect_teams(v, acc, seen)
    elif isinstance(obj, list):
        for v in obj:
            collect_teams(v, acc, seen)


def outline(obj, depth=0, max_depth=2):
    pad = "  " * depth
    if depth > max_depth:
        return
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(v, dict):
                print(f"{pad}{k}: dict({len(v)})")
                outline(v, depth + 1, max_depth)
            elif isinstance(v, list):
                print(f"{pad}{k}: list({len(v)})")
                if v and isinstance(v[0], (dict, list)):
                    outline(v[0], depth + 1, max_depth)
            else:
                print(f"{pad}{k}: {repr(v)[:60]}")


def fetch_league(lid):
    """Try the overview URL, then the bare one; return pageProps."""
    for url in (f"https://www.fotmob.com/leagues/{lid}/overview",
                f"https://www.fotmob.com/leagues/{lid}"):
        r = requests.get(url, headers=HEADERS, timeout=20)
        if r.status_code == 200:
            soup = BeautifulSoup(r.text, "lxml")
            nd = soup.find("script", id="__NEXT_DATA__")
            if nd:
                return json.loads(nd.string)["props"]["pageProps"], url
    r.raise_for_status()
    return {}, url


def teams_of(lid):
    print(f"\n=== league {lid} ===")
    pp, used = fetch_league(lid)
    print(f"  url: {used} | pageProps keys: {list(pp.keys())[:20]}")

    # the league standings live under a 'table' block; teams are id+name dicts there
    block = find_key(pp, "table") or find_key(pp, "teams") or find_key(pp, "standings")
    acc, seen = [], set()
    if block is not None:
        collect_teams(block, acc, seen)

    if acc:
        df = pd.DataFrame(acc); df["league_id"] = lid
        print(f"  teams found: {len(df)}")
        print(df[["team_id", "name"]].head(30).to_string(index=False))
        return df

    print("  !! couldn't auto-extract teams. Diagnostics:")
    print(f"  top-level pageProps keys: {list(pp.keys())[:20]}")
    print("  --- outline of the 'table' block (or None) ---")
    outline(block if block is not None else {}, max_depth=2)
    print("  >> paste this back and I'll lock the parser onto the real path")
    return pd.DataFrame()


def main(league_ids):
    frames = []
    for lid in league_ids:
        try:
            frames.append(teams_of(lid))
        except Exception as e:
            print(f"  ERR {lid}: {e}")
        time.sleep(DELAY)
    allt = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    if not allt.empty:
        allt.to_csv("fotmob_league_teams.csv", index=False)
        print(f"\nwrote {len(allt)} teams -> fotmob_league_teams.csv")
        print("next — pull all their squads:")
        print("  python fotmob_squad.py " +
              " ".join(str(t) for t in allt.team_id.tolist()))


if __name__ == "__main__":
    ids = [int(a) for a in sys.argv[1:]] or [125]      # default: Scottish League Two
    main(ids)
