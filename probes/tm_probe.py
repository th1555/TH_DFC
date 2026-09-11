#!/usr/bin/env python3
"""
Transfermarkt availability probe  —  Dumbarton SL2 recruitment engine
--------------------------------------------------------------------
Purpose: a QUICK check of whether the fields we need (name, age, position,
market value, contract expiry, and — separately — minutes/apps) are actually
retrievable from Transfermarkt for the leagues in our recruitment pool.

This is a spike, not the pipeline. Run it locally: Transfermarkt blocks cloud
IPs and rate-limits hard, so run from a normal machine, keep the delay, and
stop if you start getting 403s. Respect their ToS; cache what you pull.

    pip install requests beautifulsoup4 lxml pandas
    python tm_probe.py
"""
import time
import sys
import requests
from bs4 import BeautifulSoup

# Transfermarkt competition codes. SC1-SC4 are the SPFL tiers (verified format).
# Highland / Lowland are lower-pyramid — look their codes up by browsing TM and
# add them here; leave as None to skip.
LEAGUES = {
    "Scottish Premiership": "SC1",
    "Scottish Championship": "SC2",
    "Scottish League One":  "SC3",
    "Scottish League Two":  "SC4",
    # "Highland League":     None,   # <- fill in after checking TM
    # "Lowland League":      None,
}

BASE = "https://www.transfermarkt.com"
HEADERS = {  # a real browser UA is required or TM returns 403 immediately
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/124.0 Safari/537.36"),
    "Accept-Language": "en-US,en;q=0.9",
}
DELAY = 4.0  # seconds between requests — be polite / avoid the ban hammer


def get(url):
    r = requests.get(url, headers=HEADERS, timeout=20)
    r.raise_for_status()
    return BeautifulSoup(r.text, "lxml")


def probe_competition(name, code):
    """Fetch the competition page, list clubs, then read one club's squad
    page and report which target fields are present."""
    print(f"\n=== {name}  ({code}) ===")
    try:
        comp_url = f"{BASE}/-/startseite/wettbewerb/{code}"
        soup = get(comp_url)
        time.sleep(DELAY)

        # club links live in the competition table
        clubs = []
        for a in soup.select("td.hauptlink a[href*='/verein/']"):
            href = a.get("href", "")
            if "/verein/" in href and a.text.strip():
                clubs.append((a.text.strip(), href))
        clubs = list(dict.fromkeys(clubs))  # dedup, keep order
        print(f"  clubs found: {len(clubs)}")
        if not clubs:
            print("  !! no clubs parsed — page structure may have changed or league not on TM")
            return

        # inspect the first club's detailed squad page (has age/value/contract)
        club_name, club_href = clubs[0]
        squad_url = BASE + club_href.replace("/startseite/", "/kader/") + "/plus/1"
        squad = get(squad_url)
        time.sleep(DELAY)

        rows = squad.select("table.items > tbody > tr")
        players = [r for r in rows if r.select_one("td.posrela")]
        print(f"  sample club: {club_name}  ->  {len(players)} players parsed")

        if players:
            p = players[0]
            cells = p.find_all("td", recursive=False)
            name_el = p.select_one("td.posrela a")
            fields = {
                "name":            bool(name_el),
                "position":        bool(p.select_one("td.posrela tr:nth-of-type(2)")),
                "age/dob":         any("(" in c.get_text() for c in cells),
                "market_value":    bool(squad.select_one("td.rechts.hauptlink")),
            }
            print("  field availability on squad page:")
            for k, v in fields.items():
                print(f"    {'OK ' if v else 'MISSING'}  {k}")
            print("  note: MINUTES/APPS are NOT on this page — they live on the")
            print("        player 'Detailed stats' (leistungsdaten) page, one hop further.")
    except requests.HTTPError as e:
        print(f"  HTTP error: {e}  (403 = blocked/rate-limited; try later, slower, or a residential IP)")
    except Exception as e:
        print(f"  parse/other error: {e}")


if __name__ == "__main__":
    print("Transfermarkt availability probe — running locally")
    print("If every league 403s, TM is blocking this IP; slow DELAY down or change network.")
    for nm, cd in LEAGUES.items():
        if cd:
            probe_competition(nm, cd)
    print("\nDone. For a robust pipeline prefer worldfootballR (R, mature TM support)")
    print("or the maintained 'transfermarkt-datasets' project over hand-scraping.")
