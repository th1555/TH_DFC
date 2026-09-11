#!/usr/bin/env python3
"""
FotMob structure explorer  —  find the SEASON/CAREER totals
-----------------------------------------------------------
The first probe confirmed FotMob's data is in __NEXT_DATA__ under pageProps.data,
with match-by-match stats in `recentMatches`. But the equivalency engine needs
per-SEASON totals (minutes, goals, apps per season/competition) so we can spot
league moves. This script dumps the shape of `data` (skipping the noisy match
list) so we can see exactly where the season/career aggregates live.

Run locally:  python fotmob_probe2.py
Then paste the outline back.
"""
import json
import time
import requests
from bs4 import BeautifulSoup

PLAYER = ("Jamie Bradley (League Two)", 1724253)   # our target tier
HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/124.0 Safari/537.36"),
    "Accept-Language": "en-US,en;q=0.9",
}
SKIP = {"recentMatches"}                 # noisy match list — skip in the outline
STAT_HINTS = ("season", "career", "stat", "tournament", "league",
              "senior", "total", "item")


def outline(obj, depth=0, max_depth=3, path=""):
    pad = "  " * depth
    if depth > max_depth:
        return
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in SKIP:
                print(f"{pad}{k}: <skipped>")
                continue
            if isinstance(v, dict):
                print(f"{pad}{k}: dict({len(v)} keys)")
                outline(v, depth + 1, max_depth, f"{path}.{k}")
            elif isinstance(v, list):
                print(f"{pad}{k}: list(len {len(v)})")
                if v and isinstance(v[0], (dict, list)):
                    outline(v[0], depth + 1, max_depth, f"{path}.{k}[0]")
                elif v:
                    print(f"{pad}  e.g. {v[0]!r}")
            else:
                s = repr(v)
                print(f"{pad}{k}: {s[:70]}")


def main():
    name, pid = PLAYER
    print(f"=== structure of {name} (id {pid}) ===\n")
    r = requests.get(f"https://www.fotmob.com/players/{pid}",
                     headers=HEADERS, timeout=20)
    print(f"HTTP {r.status_code} | bytes {len(r.text)}\n")
    soup = BeautifulSoup(r.text, "lxml")
    data = json.loads(soup.find("script", id="__NEXT_DATA__").string)
    d = data["props"]["pageProps"]["data"]

    print("TOP-LEVEL keys of pageProps.data:")
    for k, v in d.items():
        t = type(v).__name__
        extra = f"(len {len(v)})" if isinstance(v, (list, dict)) else f"= {repr(v)[:50]}"
        print(f"  {k}: {t} {extra}")

    print("\n--- drilling into blocks that look like season/career stats ---")
    for k, v in d.items():
        if any(h in k.lower() for h in STAT_HINTS):
            print(f"\n[{k}]")
            outline(v, depth=1, max_depth=3, path=k)

    print("\nPaste this whole outline back — it shows where per-season "
          "minutes/goals/apps live.")


if __name__ == "__main__":
    main()
