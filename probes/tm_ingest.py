#!/usr/bin/env python3
"""
Transfermarkt ingest  —  Dumbarton recruitment engine (market layer, stage 2)
=============================================================================
Pulls date-of-birth, contract-until and market value (where it exists) for every
player in a Transfermarkt competition's clubs, into tm_market.csv. Header-aware:
it reads the squad table's headers to find the right columns, and prints the
mapping for the first club so we can confirm it locked on correctly.

Stage 3 (separate) matches these to your FotMob players by name + date of birth.

Run LOCALLY (home connection). Default competition is Scottish League Two (SC4).
    python tm_ingest.py            # SC4
    python tm_ingest.py SC3 SC4    # League One + League Two
Deps: requests, beautifulsoup4, lxml, pandas
"""
import re
import sys
import time
import requests
import pandas as pd
from bs4 import BeautifulSoup

BASE = "https://www.transfermarkt.com"
HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/124.0 Safari/537.36"),
    "Accept-Language": "en-US,en;q=0.9",
}
DELAY = 5.0
DATE = re.compile(r"\b(\d{1,2})[./](\d{1,2})[./](\d{4})\b")


def get(url):
    r = requests.get(url, headers=HEADERS, timeout=25)
    return r.status_code, BeautifulSoup(r.text, "lxml")


def iso(d):
    """dd/mm/yyyy -> yyyy-mm-dd (Transfermarkt uses day/month/year)."""
    m = DATE.search(d or "")
    return f"{m.group(3)}-{int(m.group(2)):02d}-{int(m.group(1)):02d}" if m else None


def header_map(sq):
    ths = sq.select("table.items thead th")
    labels = [((th.get("title") or th.get_text(" ", strip=True)) or "").strip().lower()
              for th in ths]
    idx = {}
    for i, l in enumerate(labels):
        if ("birth" in l or l == "age") and "dob" not in idx:
            idx["dob"] = i
        if "contract" in l:
            idx["contract"] = i
        if "market value" in l or l in ("mv", "value"):
            idx["mv"] = i
    return labels, idx


def parse_squad(sq, club):
    _, idx = header_map(sq)
    out = []
    for p in sq.select("table.items > tbody > tr"):
        pos_cell = p.select_one("td.posrela")
        if not pos_cell:
            continue
        a = pos_cell.select_one("a")
        name = a.get_text(strip=True) if a else None
        if not name:
            continue
        tds = p.find_all("td", recursive=False)
        texts = [t.get_text(" ", strip=True) for t in tds]
        row_text = " | ".join(texts)
        dates = [f"{d[0]}/{d[1]}/{d[2]}" for d in DATE.findall(row_text)]

        # date of birth: header column if known, else the first date in the row
        dob = None
        if "dob" in idx and idx["dob"] < len(texts):
            dob = iso(texts[idx["dob"]])
        dob = dob or (iso(dates[0]) if dates else None)

        # contract-until: header column if known, else last date (after dob & joined)
        contract = None
        if "contract" in idx and idx["contract"] < len(texts):
            contract = iso(texts[idx["contract"]])
        if not contract and len(dates) >= 3:
            contract = iso(dates[-1])

        # market value (often "-" at this level)
        mv_el = p.select_one("td.rechts.hauptlink")
        mv = mv_el.get_text(strip=True) if mv_el else None
        if mv in ("-", ""):
            mv = None

        m = re.search(r"/spieler/(\d+)", a["href"]) if a and a.get("href") else None
        pos = pos_cell.get_text(" ", strip=True).replace(name, "").strip()
        out.append(dict(tm_id=int(m.group(1)) if m else None, tm_name=name,
                        position=pos, dob=dob, contract_until=contract,
                        market_value=mv, club=club))
    return out


def main(comps):
    rows, first = [], True
    for comp in comps:
        st, soup = get(f"{BASE}/-/startseite/wettbewerb/{comp}")
        print(f"competition {comp}: HTTP {st}")
        if st != 200:
            print("  blocked/failed — stop and retry slower, or use a fallback.")
            continue
        clubs = []
        for x in soup.select("td.hauptlink a[href*='/verein/']"):
            if x.text.strip():
                clubs.append((x.text.strip(), x["href"]))
        clubs = list(dict.fromkeys(clubs))
        print(f"  clubs: {len(clubs)}")
        time.sleep(DELAY)
        for club, href in clubs:
            st2, sq = get(BASE + href.replace("/startseite/", "/kader/") + "/plus/1")
            if st2 != 200:
                print(f"    {club}: HTTP {st2} (skipped)"); time.sleep(DELAY); continue
            if first:
                labels, idx = header_map(sq)
                print(f"    [check] header columns: {labels}")
                print(f"    [check] locked on -> {idx}")
                first = False
            players = parse_squad(sq, club)
            rows += players
            print(f"    {club}: {len(players)} players")
            time.sleep(DELAY)
    df = pd.DataFrame(rows)
    df.to_csv("tm_market.csv", index=False)
    have_c = df.contract_until.notna().sum() if len(df) else 0
    have_v = df.market_value.notna().sum() if len(df) else 0
    print(f"\nwrote {len(df)} players -> tm_market.csv "
          f"({have_c} with contract dates, {have_v} with market values)")


if __name__ == "__main__":
    main([a.upper() for a in sys.argv[1:]] or ["SC4"])
