#!/usr/bin/env python3
"""
FotMob field dump  —  see the exact per-season fields
-----------------------------------------------------
Prints the raw JSON of just the blocks that hold aggregates, so we can read the
exact field names (esp. whether MINUTES is in the per-season history or only in
recentMatches). This is the last recon before the real ingestion pull.

Run locally:  python fotmob_probe3.py    (paste the output back)
"""
import json
import requests
from bs4 import BeautifulSoup

PLAYER_ID = 1724253                       # Jamie Bradley, League Two
HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/124.0 Safari/537.36"),
    "Accept-Language": "en-US,en;q=0.9",
}


def show(label, obj, limit=1600):
    print(f"\n{'='*8} {label} {'='*8}")
    if obj is None:
        print("  (missing)")
        return
    s = json.dumps(obj, indent=2, ensure_ascii=False)
    print(s[:limit] + (" …(truncated)" if len(s) > limit else ""))


def main():
    r = requests.get(f"https://www.fotmob.com/players/{PLAYER_ID}",
                     headers=HEADERS, timeout=20)
    print(f"HTTP {r.status_code} | bytes {len(r.text)}")
    soup = BeautifulSoup(r.text, "lxml")
    d = json.loads(soup.find("script", id="__NEXT_DATA__").string)
    d = d["props"]["pageProps"]["data"]

    senior = (d.get("careerHistory", {}) or {}).get("careerItems", {}).get("senior", {})

    show("mainLeague", d.get("mainLeague"))
    show("seasonEntries (per-season history)", senior.get("seasonEntries"))
    show("teamEntries[:2]", (senior.get("teamEntries") or [])[:2])
    show("statSeasons", d.get("statSeasons"))
    show("firstSeasonStats", d.get("firstSeasonStats"))
    show("recentMatches[0] (one full match)", (d.get("recentMatches") or [None])[0])
    print("\nmatchesUrl:", d.get("matchesUrl"))
    print("\nPaste this whole dump back — it names the exact fields to read.")


if __name__ == "__main__":
    main()
