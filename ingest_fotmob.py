#!/usr/bin/env python3
"""
FotMob ingestion pull  —  Dumbarton SL2 recruitment engine (data layer)
=======================================================================
Turns FotMob player pages into the tidy player-season table the equivalency
engine consumes. Reads the embedded __NEXT_DATA__ JSON (confirmed working from
a home IP), and pulls per-SEASON, per-COMPETITION output from
`seasonEntries[].tournamentStats[]`: appearances, goals, assists — split by
league, which is exactly what cross-league equivalency needs.

Honest data note (confirmed by probing real SL2 players):
  * appearances / goals / assists per league per season  -> reliably present
  * MINUTES per season                                    -> NOT in the season
    aggregates; only current-season minutes are on the page (mainLeague). Full
    per-season minutes require aggregating the match feed (matchesUrl) — left as
    an optional enrichment. So the primary output rate here is PER-APPEARANCE
    goal contributions, with per-90 filled only where minutes are known. The
    spec anticipated exactly this fallback at fourth-tier level.

Usage:
  python ingest_fotmob.py --selftest         # parse a bundled REAL sample, no network
  python ingest_fotmob.py 1724253 1609202    # pull real players by FotMob id -> CSV

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

# Scottish league tournament IDs seen on FotMob (extend as needed).
# Cups (e.g. Challenge Cup 179) are captured but flagged is_cup so the
# equivalency step can exclude them — league form only.
KNOWN_LEAGUES = {123: "Championship", 125: "League Two"}   # + 124 L1, 66 Prem etc.
CUP_LEAGUE_IDS = {179}                                      # Challenge Cup, etc.


def _age_from(dob):
    """Best-effort age from FotMob birthDate (shape not guaranteed)."""
    from datetime import date
    if not isinstance(dob, dict):
        return None
    y = m = d = None
    t = dob.get("utcTime")
    if isinstance(t, str) and len(t) >= 4 and t[:4].isdigit():
        y = int(t[:4])
        m = int(t[5:7]) if len(t) >= 7 and t[5:7].isdigit() else 1
        d = int(t[8:10]) if len(t) >= 10 and t[8:10].isdigit() else 1
    elif dob.get("year"):
        y = int(dob["year"]); m = int(dob.get("month", 1)); d = int(dob.get("day", 1))
    if not y:
        return None
    today = date.today()
    return today.year - y - ((today.month, today.day) < (m, d))


def _int(x, default=0):
    try:
        return int(str(x).strip())
    except (ValueError, TypeError):
        return default


def current_minutes(data: dict):
    """Current-season minutes total from mainLeague (the only minutes on the
    page). Returns (season, league_id, minutes) or None."""
    ml = data.get("mainLeague") or {}
    stats = {s.get("localizedTitleId"): s.get("value") for s in (ml.get("stats") or [])}
    if "minutes_played" in stats:
        return ml.get("season"), ml.get("leagueId"), _int(stats["minutes_played"])
    return None


def parse_player(data: dict) -> list[dict]:
    """Flatten one player's __NEXT_DATA__ 'data' block into per-season,
    per-competition rows."""
    if not data:
        return []
    pid = data.get("id")
    name = data.get("name")
    age = _age_from(data.get("birthDate"))
    pos = ((data.get("positionDescription") or {}).get("primaryPosition") or {}).get("label")

    cur = current_minutes(data)                       # (season, leagueId, minutes)
    senior = ((data.get("careerHistory") or {}).get("careerItems") or {}).get("senior") or {}

    rows = []
    for se in (senior.get("seasonEntries") or []):
        season = se.get("seasonName")
        team = se.get("team")
        transfer = (se.get("transferType") or {}).get("text")
        for t in (se.get("tournamentStats") or []):
            if t.get("isFriendly"):
                continue
            lid = t.get("leagueId")
            apps = _int(t.get("appearances"))
            goals = _int(t.get("goals"))
            assists = _int(t.get("assists"))
            gc = goals + assists
            minutes = None
            if cur and season == cur[0] and lid == cur[1]:
                minutes = cur[2]                       # fill current-season minutes
            rows.append(dict(
                player_id=pid, player_name=name, position=pos, age=age,
                season=season, league=t.get("leagueName"), league_id=lid,
                tournament_id=t.get("tournamentId"), team=team,
                appearances=apps, goals=goals, assists=assists, goal_contribs=gc,
                per_app=round(gc / apps, 3) if apps else 0.0,
                minutes=minutes,
                per90=round(gc / minutes * 90, 3) if minutes else None,
                is_cup=lid in CUP_LEAGUE_IDS,
                transfer_type=transfer,
            ))
    return rows


def fetch_player(pid: int) -> dict:
    r = requests.get(f"https://www.fotmob.com/players/{pid}",
                     headers=HEADERS, timeout=20)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "lxml")
    nd = soup.find("script", id="__NEXT_DATA__")
    return json.loads(nd.string)["props"]["pageProps"]["data"]


def pull(ids: list[int], out="fotmob_player_seasons.csv") -> pd.DataFrame:
    rows = []
    for pid in ids:
        try:
            rows += parse_player(fetch_player(pid))
            print(f"  ok  {pid}")
        except Exception as e:
            print(f"  ERR {pid}: {e}")
        time.sleep(DELAY)
    df = pd.DataFrame(rows)
    df.to_csv(out, index=False)
    print(f"\nwrote {len(df)} rows -> {out}")
    return df


# ---------------------------------------------------------------------------
# Offline self-test on a REAL sample (from probing Jamie Bradley, id 1724253)
# so the parser is validated without touching the network.
# ---------------------------------------------------------------------------
SAMPLE = {
    "id": 1724253, "name": "Jamie Bradley",
    "mainLeague": {"leagueId": 125, "leagueName": "League Two", "season": "2026/2027",
                   "stats": [{"localizedTitleId": "goals", "value": 0},
                             {"localizedTitleId": "assists", "value": 0},
                             {"localizedTitleId": "minutes_played", "value": 56}]},
    "careerHistory": {"careerItems": {"senior": {"seasonEntries": [
        {"seasonName": "2026/2027", "team": "Clyde",
         "transferType": {"text": "free transfer"},
         "tournamentStats": [
             {"isFriendly": False, "leagueId": 125, "leagueName": "League Two",
              "tournamentId": 36853, "goals": "0", "assists": "0", "appearances": "1"},
             {"isFriendly": False, "leagueId": 179, "leagueName": "Challenge Cup",
              "tournamentId": 45504, "goals": "0", "assists": "0", "appearances": "2"}]},
        {"seasonName": "2025/2026", "team": "Queen's Park",
         "transferType": {"text": "back from loan"},
         "tournamentStats": [
             {"isFriendly": False, "leagueId": 123, "leagueName": "Championship",
              "tournamentId": 27154, "goals": "1", "assists": "2", "appearances": "6"},
             {"isFriendly": False, "leagueId": 179, "leagueName": "Challenge Cup",
              "tournamentId": 45504, "goals": "0", "assists": "0", "appearances": "3"}]},
    ]}}},
}


def selftest():
    print("SELF-TEST — parsing a real bundled sample (no network)\n")
    df = pd.DataFrame(parse_player(SAMPLE))
    cols = ["season", "league", "league_id", "appearances", "goals", "assists",
            "goal_contribs", "per_app", "minutes", "per90", "is_cup", "transfer_type"]
    print(df[cols].to_string(index=False))
    print("\nChecks:")
    print(f"  rows parsed: {len(df)} (expect 4)")
    champ = df[(df.season == '2025/2026') & (df.league_id == 123)].iloc[0]
    print(f"  2025/26 Championship per_app = {champ.per_app}  (expect 0.5 = (1+2)/6)")
    cur = df[(df.season == '2026/2027') & (df.league_id == 125)].iloc[0]
    print(f"  2026/27 League Two minutes  = {cur.minutes}  (expect 56, filled from mainLeague)")
    print(f"  cup rows flagged is_cup: {int(df.is_cup.sum())}  (expect 2)")


if __name__ == "__main__":
    args = sys.argv[1:]
    if not args or args[0] == "--selftest":
        selftest()
    elif args[0] == "--from-csv":                       # read ids from a squad CSV
        ids = pd.read_csv(args[1]).player_id.astype(int).tolist()
        print(f"Pulling {len(ids)} player(s) from {args[1]} …  (~{len(ids)*3//60}+ min)")
        pull(ids)
    else:
        ids = [int(a) for a in args]
        print(f"Pulling {len(ids)} player(s) from FotMob…")
        pull(ids)
