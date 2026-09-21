#!/usr/bin/env python3
"""
FotMob squad pull  —  Dumbarton SL2 recruitment engine (roster layer)
=====================================================================
Given a FotMob TEAM id, return the squad as a list of (player_id, name, role)
so you can feed those ids straight into ingest_fotmob.py — turning "a few
players" into "the whole league" without typing ids by hand.

Diagnostic-first: the team-page JSON structure hasn't been eyeballed yet, so if
the auto-extract misses, this prints the shape of the squad block (and the
top-level keys) so we can lock the parser in one pass. Paste that back if so.

Usage:
  python fotmob_squad.py            # defaults to Clyde (8409), a real L2 club
  python fotmob_squad.py 8409 8235  # one or more team ids -> squad CSV

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
DEFAULT_TEAMS = [8409]        # Clyde


def find_key(obj, key):
    """First value found under `key` anywhere in the tree."""
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


def collect_players(obj, acc, seen):
    """Within a subtree, gather dicts that look like squad members
    (int id + str name)."""
    if isinstance(obj, dict):
        pid, nm = obj.get("id"), obj.get("name")
        if isinstance(pid, int) and isinstance(nm, str) and nm:
            role = obj.get("role")
            if isinstance(role, dict):
                rkey = str(role.get("key", "")); rlabel = role.get("fallback") or rkey
            else:
                rkey = str(role or ""); rlabel = role
            if pid not in seen and "coach" not in rkey.lower():   # players only
                seen.add(pid)
                acc.append({"player_id": pid, "name": nm, "position": rlabel})
        for v in obj.values():
            collect_players(v, acc, seen)
    elif isinstance(obj, list):
        for v in obj:
            collect_players(v, acc, seen)


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
    elif isinstance(obj, list):
        if obj and isinstance(obj[0], (dict, list)):
            outline(obj[0], depth, max_depth)


def fetch_team(tid: int) -> dict:
    r = requests.get(f"https://www.fotmob.com/teams/{tid}",
                     headers=HEADERS, timeout=20)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "lxml")
    nd = soup.find("script", id="__NEXT_DATA__")
    return json.loads(nd.string)["props"]["pageProps"]   # keys vary by page type


def squad_of(tid: int) -> pd.DataFrame:
    print(f"\n=== team {tid} ===")
    pp = fetch_team(tid)
    print(f"  pageProps keys: {list(pp.keys())[:20]}")
    data = pp.get("data", pp)                     # team data may sit under 'data' or not
    squad_block = find_key(data, "squad") or find_key(pp, "squad")

    acc, seen = [], set()
    if squad_block is not None:
        collect_players(squad_block, acc, seen)

    if acc:
        df = pd.DataFrame(acc)
        df["team_id"] = tid
        print(f"  players found: {len(df)}")
        print(df[["player_id", "name", "position"]].head(40).to_string(index=False))
        return df

    # auto-extract missed — dump structure so we can lock it
    print("  !! couldn't auto-extract players. Diagnostics:")
    print(f"  top-level data keys: {list(data.keys())[:20]}")
    print("  --- outline of the 'squad' block (or None) ---")
    outline(squad_block if squad_block is not None else {}, max_depth=2)
    print("  >> paste this back and I'll lock the parser onto the real path")
    return pd.DataFrame()


def main(team_ids):
    frames = []
    for tid in team_ids:
        try:
            frames.append(squad_of(tid))
        except Exception as e:
            print(f"  ERR {tid}: {e}")
        time.sleep(DELAY)
    allsq = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    if not allsq.empty:
        allsq.to_csv("fotmob_squad.csv", index=False)
        print(f"\nwrote {len(allsq)} players -> fotmob_squad.csv")
        att = allsq[allsq.position.astype(str).str.contains("Attack", case=False, na=False)]
        print("\nnext — pull the whole squad:")
        print("  python ingest_fotmob.py " + " ".join(map(str, allsq.player_id.tolist())))
        if not att.empty:
            print("\nor V1 (strikers only) — pull just the attackers:")
            print("  python ingest_fotmob.py " + " ".join(map(str, att.player_id.tolist())))


if __name__ == "__main__":
    ids = [int(a) for a in sys.argv[1:]] or DEFAULT_TEAMS
    main(ids)
