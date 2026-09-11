#!/usr/bin/env python3
"""
FotMob availability probe  —  Dumbarton SL2 recruitment engine
--------------------------------------------------------------
Goal: confirm we can pull the PRODUCTIVITY layer (goals, assists, appearances,
MINUTES, per season) for real Scottish lower-league players, in plain Python.

FotMob is a Next.js app that embeds its data as JSON in the page. This probe
fetches a few real Scottish players (seeded below — League Two / One / Champ),
finds that embedded JSON, and then RECURSIVELY SEARCHES it for anything that
looks like minutes/goals/apps, printing the exact path so we can lock the
parser onto it in one pass. It also tries the JSON API endpoint as a fallback.

Run locally (FotMob, like TM, may block cloud IPs — run from home):
    pip install requests beautifulsoup4 lxml
    python fotmob_probe.py

Then paste the output back — the [hit] paths tell us exactly where the data is.
"""
import json
import re
import time
import requests
from bs4 import BeautifulSoup

# Real FotMob player IDs (from public pages) across the tiers we care about.
PLAYERS = {
    "Jamie Bradley (League Two)":   1724253,
    "Callum Penman (League One)":   1609202,
    "Ryan Duncan (Championship)":   1210371,
}

HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/124.0 Safari/537.36"),
    "Accept-Language": "en-US,en;q=0.9",
}
DELAY = 3.0
NEEDLES = ["minut", "goal", "assist", "appear", "matches", "started"]


def get(url):
    r = requests.get(url, headers=HEADERS, timeout=20)
    return r.status_code, r.text


def find_keys(obj, needles, path="", hits=None, cap=25):
    """Recursively walk parsed JSON; record paths whose KEY matches a needle."""
    if hits is None:
        hits = []
    if len(hits) >= cap:
        return hits
    if isinstance(obj, dict):
        for k, v in obj.items():
            p = f"{path}.{k}"
            if any(n in str(k).lower() for n in needles):
                sample = v if not isinstance(v, (dict, list)) else f"<{type(v).__name__}>"
                hits.append((p, sample))
            find_keys(v, needles, p, hits, cap)
    elif isinstance(obj, list):
        for i, v in enumerate(obj[:6]):     # sample first few list items
            find_keys(v, needles, f"{path}[{i}]", hits, cap)
    return hits


def probe(name, pid):
    print(f"\n=== {name}  (id {pid}) ===")
    try:
        status, html = get(f"https://www.fotmob.com/players/{pid}")
        print(f"  page GET: HTTP {status} | bytes {len(html)}")
        soup = BeautifulSoup(html, "lxml")

        # 1) Pages-Router embedded JSON
        nd = soup.find("script", id="__NEXT_DATA__")
        if nd and nd.string:
            data = json.loads(nd.string)
            props = data.get("props", {}).get("pageProps", {})
            print(f"  __NEXT_DATA__: found | pageProps keys: {list(props.keys())[:12]}")
            hits = find_keys(props, NEEDLES)
            if hits:
                print("  [hit] embedded JSON paths that look like stats:")
                for p, s in hits[:15]:
                    print(f"     {p} = {s}")
            else:
                print("  no stat-like keys inside __NEXT_DATA__ (data may load via API)")
        else:
            # 2) App-Router: data streamed differently; check it's at least present
            print("  __NEXT_DATA__: NOT present (likely App Router)")
            print(f"  raw HTML mentions 'minut': {'minut' in html.lower()}")

        time.sleep(DELAY)

        # 3) JSON API fallback — tells us if the header-free API still works
        s2, body = get(f"https://www.fotmob.com/api/playerData?id={pid}")
        print(f"  api/playerData: HTTP {s2}", end="")
        if s2 == 200:
            try:
                j = json.loads(body)
                hits = find_keys(j, NEEDLES)
                print(" | JSON OK")
                for p, sm in hits[:10]:
                    print(f"     [api] {p} = {sm}")
            except Exception:
                print(" | body not JSON")
        else:
            print(" | (non-200 usually means it now needs the x-mas header)")
        time.sleep(DELAY)

    except requests.HTTPError as e:
        print(f"  HTTP error: {e}")
    except Exception as e:
        print(f"  error: {e}")


if __name__ == "__main__":
    print("FotMob availability probe — running locally")
    for nm, pid in PLAYERS.items():
        probe(nm, pid)
    print("\nRead-out: wherever you see a [hit] path containing 'minutes',")
    print("that's the field we wire the real pull onto. Paste this back.")
