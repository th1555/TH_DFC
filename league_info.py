#!/usr/bin/env python3
"""
league_info.py  —  look up the country of every league in your data
===================================================================
Leagues are kept apart by their FotMob id, so English League Two can never be
mixed up with Scottish League Two. This script just makes the labels readable:
it visits each league's FotMob page once and records its country, so the site
shows "Championship (England)" instead of "Championship (league 48)".

Run it at home (FotMob blocks cloud servers), after an ingest and before
store_pipeline.py. Rerun it whenever new leagues appear in your data.

    python league_info.py                      # reads fotmob_player_seasons.csv
    python league_info.py other_seasons.csv

Writes league_countries.csv (league_id, name, country). Leagues already in that
file are skipped, so reruns are quick.
Deps: requests, beautifulsoup4, lxml, pandas
"""
import json
import os
import sys
import time
import requests
import pandas as pd
from bs4 import BeautifulSoup

OUT = "league_countries.csv"
DELAY = 3.0
HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"),
    "Accept-Language": "en-US,en;q=0.9",
}
CODES = {"SCO": "Scotland", "ENG": "England", "IRL": "Ireland", "NIR": "Northern Ireland",
         "WAL": "Wales", "USA": "USA", "CAN": "Canada", "AUS": "Australia", "NZL": "New Zealand",
         "ISL": "Iceland", "NOR": "Norway", "SWE": "Sweden", "FIN": "Finland", "DEN": "Denmark",
         "NED": "Netherlands", "BEL": "Belgium", "GER": "Germany", "ESP": "Spain", "FRA": "France",
         "ITA": "Italy", "POR": "Portugal", "FRO": "Faroe Islands", "GIB": "Gibraltar",
         "MLT": "Malta", "CYP": "Cyprus", "IND": "India", "THA": "Thailand", "HKG": "Hong Kong"}


def country_from(details):
    """Defensive: FotMob's field names are not guaranteed."""
    if not isinstance(details, dict):
        return None
    for key in ("country", "countryName", "ccode", "countryCode"):
        v = details.get(key)
        if isinstance(v, str) and v.strip():
            v = v.strip()
            return CODES.get(v.upper(), v)
    return None


def main(src):
    df = pd.read_csv(src)
    df = df[df.league_id.fillna(0).astype(int) > 0]
    df = df[~df.league.astype(str).str.lower().str.contains("cup")]
    leagues = (df.groupby("league_id").league.first().reset_index())
    have = pd.read_csv(OUT) if os.path.exists(OUT) else pd.DataFrame(columns=["league_id", "name", "country"])
    known = set(have.league_id.astype(int))
    todo = [(int(i), n) for i, n in zip(leagues.league_id, leagues.league) if int(i) not in known]
    print(f"{len(leagues)} leagues in data, {len(todo)} to look up (~{len(todo)*DELAY/60:.0f} min)")

    rows, shown = [], False
    for lid, name in todo:
        country = None
        try:
            r = requests.get(f"https://www.fotmob.com/leagues/{lid}/overview", headers=HEADERS, timeout=20)
            nd = BeautifulSoup(r.text, "lxml").find("script", id="__NEXT_DATA__")
            pp = json.loads(nd.string)["props"]["pageProps"] if nd else {}
            country = country_from(pp.get("details"))
            if country is None and not shown:
                d = pp.get("details")
                print(f"  [check] no country field found; details keys: "
                      f"{list(d.keys())[:20] if isinstance(d, dict) else type(d).__name__}"
                      "  <- paste this line back if most leagues come out blank")
                shown = True
        except Exception as e:
            print(f"  {lid} {name}: error {e}")
        print(f"  {lid:>7}  {name:<32} {country or '(unknown)'}")
        rows.append(dict(league_id=lid, name=name, country=country))
        time.sleep(DELAY)

    out = pd.concat([have, pd.DataFrame(rows)], ignore_index=True)
    out.to_csv(OUT, index=False)
    print(f"\nwrote {OUT}: {out.country.notna().sum()} of {len(out)} leagues have a country")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "fotmob_player_seasons.csv")
