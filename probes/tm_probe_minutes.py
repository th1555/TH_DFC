#!/usr/bin/env python3
"""
Transfermarkt MINUTES/APPS probe  (v3)
--------------------------------------
Fix vs v2: build the performance URL from the player's REAL profile link
(correct slug), instead of a dummy 'x' slug — TM serves the stats table only
on the properly-slugged URL. Still self-diagnosing: if no table is found it now
dumps every table's class, whether the HTML mentions 'minut', and the page
title, so we can tell "wrong selector" from "JS-loaded" from "consent wall".

    pip install requests beautifulsoup4 lxml pandas
    python tm_probe_minutes.py
"""
import re
import time
import requests
from bs4 import BeautifulSoup

LEAGUES = {
    "Scottish Premiership": "SC1",   # control tier
    "Scottish League Two":  "SC4",
}
SEASON = "2025"

BASE = "https://www.transfermarkt.com"
HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/124.0 Safari/537.36"),
    "Accept-Language": "en-US,en;q=0.9",
}
DELAY = 4.0
DIAGNOSTIC = True

TARGETS = {
    "appearances": ["appearances", "matches", "spiele", "einsätze"],
    "goals":       ["goals", "tore"],
    "assists":     ["assists", "vorlagen"],
    "minutes":     ["minutes", "minutes played", "minuten"],
}


def get(url):
    r = requests.get(url, headers=HEADERS, timeout=20)
    r.raise_for_status()
    return BeautifulSoup(r.text, "lxml")


def first_player(code):
    """league -> first club -> squad -> (name, id, real_profile_href)."""
    soup = get(f"{BASE}/-/startseite/wettbewerb/{code}")
    time.sleep(DELAY)
    club = soup.select_one("td.hauptlink a[href*='/verein/']")
    if not club:
        return None
    squad = get(BASE + club["href"].replace("/startseite/", "/kader/") + "/plus/1")
    time.sleep(DELAY)
    link = squad.select_one("td.posrela a[href*='/profil/spieler/']")
    if not link:
        return None
    m = re.search(r"/spieler/(\d+)", link["href"])
    return (link.text.strip(), m.group(1), link["href"]) if m else None


def fetch_perf(profile_href, pid):
    """Prefer the correctly-slugged URL derived from the profile link."""
    cands = []
    if profile_href:
        base = profile_href.replace("/profil/spieler/", "/leistungsdaten/spieler/")
        cands += [
            f"{BASE}{base}/plus/1?saison={SEASON}",
            f"{BASE}{base}/saison/{SEASON}/plus/1",
            f"{BASE}{base}",
        ]
    cands.append(f"{BASE}/x/leistungsdaten/spieler/{pid}/plus/1?saison={SEASON}")
    last = None
    for u in cands:
        soup = get(u)
        time.sleep(DELAY)
        last = (soup, u)
        if soup.select_one("table.items tbody tr"):
            return soup, u
    return last


def header_labels(table):
    labels = []
    ths = table.select("thead th") or (
        table.select_one("tr").select("th, td") if table.select_one("tr") else [])
    for th in ths:
        parts = []
        if th.get("title"):
            parts.append(th["title"])
        for el in th.select("[title]"):
            if el.get("title"):
                parts.append(el["title"])
        txt = th.get_text(" ", strip=True)
        if txt:
            parts.append(txt)
        labels.append(" | ".join(parts).strip().lower())
    return labels


def probe(name, code):
    print(f"\n=== {name}  ({code})  season {SEASON}/{int(SEASON)+1-2000:02d} ===")
    try:
        who = first_player(code)
        if not who:
            print("  !! couldn't reach a player")
            return
        player, pid, href = who
        soup, used = fetch_perf(href, pid)
        print(f"  sample player: {player}  (id {pid})")
        if DIAGNOSTIC:
            print(f"  [diag] url used: {used}")

        tables = soup.select("table.items")
        if not tables:
            # disambiguate: wrong selector vs JS-loaded vs consent wall
            all_t = soup.find_all("table")
            classes = [ " ".join(t.get("class", [])) or "(no class)" for t in all_t ]
            print(f"  [diag] table.items: 0 | total <table>: {len(all_t)} | classes: {classes[:10]}")
            print(f"  [diag] HTML mentions 'minut': {'minut' in str(soup).lower()}"
                  f" | title: {soup.title.string.strip() if soup.title and soup.title.string else None}")
            print("  !! no items table — paste these [diag] lines back")
            return

        table = tables[0]
        labels = header_labels(table)
        if DIAGNOSTIC:
            print(f"  [diag] header labels: {labels}")
            row = table.select_one("tbody tr")
            cells = [c.get_text(' ', strip=True) for c in row.select('td')] if row else []
            print(f"  [diag] first row cells: {cells[:12]}")

        blob = " ".join(labels)
        found = {f: any(k in blob for k in kws) for f, kws in TARGETS.items()}
        print("  performance-page field availability:")
        for f in ("appearances", "goals", "assists", "minutes"):
            print(f"    {'OK ' if found[f] else 'MISSING'}  {f}")
    except requests.HTTPError as e:
        print(f"  HTTP error: {e}")
    except Exception as e:
        print(f"  parse/other error: {e}")


if __name__ == "__main__":
    print("Transfermarkt minutes/apps probe v3 — running locally")
    for nm, cd in LEAGUES.items():
        probe(nm, cd)
