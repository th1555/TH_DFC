#!/usr/bin/env python3
"""
match_market.py  —  Dumbarton recruitment engine (market layer, stage 3)
========================================================================
Joins Transfermarkt players (tm_market.csv, from tm_ingest.py) to the FotMob
players already in the store, then writes contract/availability into the
market_data table. The two sites share no IDs, so we match on NAME + DATE OF
BIRTH (reliable), falling back to NAME + BIRTH YEAR when a FotMob DOB is missing.

Availability is derived from the contract-until date:
  lapsed / expiring (<= ~8 months) / contracted / unknown.

Run (locally, after tm_ingest.py and after the store is built):
    python match_market.py            # reads tm_market.csv + dumbarton.db
Deps: pandas  (+ db.py, and a built dumbarton.db)
"""
import re
import sys
import unicodedata
from datetime import date
import pandas as pd
import db


def norm(s):
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode()
    s = re.sub(r"[^a-z\s]", " ", s.lower())
    return " ".join(s.split())


def birth_year_from_age(age):
    try:
        return date.today().year - int(age)
    except (TypeError, ValueError):
        return None


def availability(contract_iso):
    if not contract_iso or not re.match(r"\d{4}-\d{2}-\d{2}", str(contract_iso)):
        return "unknown"
    y, m, d = map(int, str(contract_iso)[:10].split("-"))
    cu, today = date(y, m, d), date.today()
    if cu < today:
        return "lapsed"                       # ended — likely free (or stale on TM)
    months = (cu.year - today.year) * 12 + (cu.month - today.month)
    return "expiring" if months <= 8 else "contracted"


def match(tm, players):
    """Return matched rows (with FotMob player_id) + a coverage report."""
    idx = {}
    for _, p in players.iterrows():
        idx.setdefault(norm(p["name"]), []).append(p)
    matched, report = [], {"dob": 0, "year": 0, "name_only": 0,
                           "ambiguous": 0, "unmatched": 0}
    for _, t in tm.iterrows():
        cands = idx.get(norm(t.tm_name), [])
        pick, how = None, None
        tm_year = int(str(t.dob)[:4]) if pd.notna(t.dob) and str(t.dob)[:4].isdigit() else None
        if not cands:
            report["unmatched"] += 1
            continue
        # 1) exact DOB
        exact = [c for c in cands if pd.notna(c.get("dob")) and str(c["dob"])[:10] == str(t.dob)[:10]]
        if len(exact) == 1:
            pick, how = exact[0], "dob"
        elif tm_year is not None:
            # 2) birth-year (from FotMob dob or age), tolerate +-1
            yr = []
            for c in cands:
                cy = int(str(c["dob"])[:4]) if pd.notna(c.get("dob")) and str(c["dob"])[:4].isdigit() \
                    else birth_year_from_age(c.get("age"))
                if cy is not None and abs(cy - tm_year) <= 1:
                    yr.append(c)
            if len(yr) == 1:
                pick, how = yr[0], "year"
        if pick is None and len(cands) == 1 and how is None:
            pick, how = cands[0], "name_only"     # single same-name, no dob to check
        elif pick is None and len(cands) > 1:
            report["ambiguous"] += 1
            continue
        if pick is None:
            report["unmatched"] += 1
            continue
        report[how] += 1
        matched.append(dict(
            player_id=int(pick["player_id"]), age=pick.get("age"),
            market_value=(None if pd.isna(t.market_value) else t.market_value),
            contract_expiry=(None if pd.isna(t.contract_until) else t.contract_until),
            availability=availability(t.contract_until), match=how))
    return pd.DataFrame(matched), report


def main(tm_path="tm_market.csv"):
    tm = pd.read_csv(tm_path)
    conn = db.connect(); db.init_db(conn)
    players = db.get_players_min(conn)
    print(f"Transfermarkt players: {len(tm)}  |  FotMob players in store: {len(players)}")

    m, rep = match(tm, players)
    print("\nmatch results:")
    for k in ("dob", "year", "name_only", "ambiguous", "unmatched"):
        print(f"  {k:<10} {rep[k]}")
    conf = rep["dob"] + rep["year"] + rep["name_only"]
    print(f"  -> matched {conf} of {len(tm)} "
          f"({rep['dob']} on exact DOB, {rep['year']} on birth-year, "
          f"{rep['name_only']} on name only)")

    if len(m):
        db.upsert_market(conn, m)
        avail = m.availability.value_counts().to_dict()
        print(f"\nwrote {len(m)} rows -> market_data.  Availability: {avail}")
        gettable = m[m.availability.isin(["expiring", "lapsed"])]
        print(f"potentially gettable (expiring soon / out of contract): {len(gettable)}")
    else:
        print("\nno confident matches — check name formatting, or ensure the store "
              "has FotMob DOBs (re-run the FotMob ingest so DOB is captured).")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "tm_market.csv")
