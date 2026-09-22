#!/usr/bin/env python3
"""
Transfermarkt MARKET probe  —  Dumbarton recruitment engine (market layer, stage 1)
===================================================================================
Go/no-go test for the Transfermarkt layer. It navigates to a real Scottish
League Two club's DETAILED squad page and checks whether we can pull the fields
we need: player name, date of birth, market value, and contract-until.

Diagnostic-first: TM blocks hard and changes its markup, so for the first few
players it DUMPS every cell in the row, so we can see exactly where each field
lives and lock the parser in one pass. Paste the output back.

Run LOCALLY (TM blocks datacenter IPs — must be your home connection):
    pip install requests beautifulsoup4 lxml
    python tm_market_probe.py
"""
import re
import time
import requests
from bs4 import BeautifulSoup

BASE = "https://www.transfermarkt.com"
COMP = "SC4"                       # Scottish League Two
HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/124.0 Safari/537.36"),
    "Accept-Language": "en-US,en;q=0.9",
}
DELAY = 5.0                        # be slow — TM is touchy
DATE = re.compile(r"\b\d{1,2}[./]\d{1,2}[./]\d{2,4}\b|\b[A-Z][a-z]{2} \d{1,2}, \d{4}\b")
MONEY = re.compile(r"[€£$]\s?[\d.,]+\s?[kmbn]?", re.I)


def get(url):
    r = requests.get(url, headers=HEADERS, timeout=25)
    return r.status_code, BeautifulSoup(r.text, "lxml")


def main():
    print("Transfermarkt MARKET probe — running locally\n")
    # 1) competition page -> first club
    st, soup = get(f"{BASE}/-/startseite/wettbewerb/{COMP}")
    print(f"competition page: HTTP {st}")
    if st == 403:
        print(">> BLOCKED (403). TM is refusing your IP. Try again slower, or from a\n"
              "   different network. If it stays blocked, we switch to worldfootballR\n"
              "   or the transfermarkt-datasets project instead of live scraping.")
        return
    club = soup.select_one("td.hauptlink a[href*='/verein/']")
    if not club:
        print("!! couldn't find a club link — paste the output; TM markup may have moved.")
        return
    club_name, href = club.text.strip(), club["href"]
    print(f"sample club: {club_name}")
    time.sleep(DELAY)

    # 2) detailed squad page (has DOB / market value / contract-until)
    squad_url = BASE + href.replace("/startseite/", "/kader/") + "/plus/1"
    st2, sq = get(squad_url)
    print(f"detailed squad page: HTTP {st2}  ({squad_url})")
    if st2 == 403:
        print(">> squad page BLOCKED. Same fallback note as above.")
        return

    rows = sq.select("table.items > tbody > tr")
    players = [r for r in rows if r.select_one("td.posrela")]
    print(f"players parsed on squad page: {len(players)}\n")
    if not players:
        print("!! no players parsed. table.items count:", len(sq.select('table.items')))
        print("   header labels:", [th.get_text(' ', strip=True)
                                     for th in sq.select('table.items thead th')][:15])
        print("   >> paste this back and I'll retarget the parser.")
        return

    # 3) DUMP the first few players' rows so we can see the column layout
    print("=== first 3 players — every cell (so we can locate DOB / value / contract) ===")
    for p in players[:3]:
        name_el = p.select_one("td.posrela a")
        name = name_el.get_text(strip=True) if name_el else "?"
        cells = [c.get_text(" ", strip=True) for c in p.find_all("td", recursive=False)]
        text = " | ".join(c for c in cells if c)
        print(f"\nPLAYER: {name}")
        print(f"  cells: {text[:400]}")
        print(f"  dates found: {DATE.findall(text)}   money found: {MONEY.findall(text)}")
    print("\nRead-out: the 'dates found' should include a birth date and a "
          "contract-until date; 'money found' should include a market value. "
          "Paste this whole output back.")


if __name__ == "__main__":
    main()
