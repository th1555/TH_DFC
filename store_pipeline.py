#!/usr/bin/env python3
"""
store_pipeline.py  —  run the whole recruitment flow through the store
======================================================================
One entry point that takes a FotMob ingest CSV and drives everything through
the SQLite store (db.py), reusing the VALIDATED engines:
  1. load player-season stats into the store (accumulating, provenance-stamped)
  2. compute league-equivalency coefficients from the store  (league_equivalency)
  3. surface strikers who fit the proven-SL2 profile           (fit ranking)
  4. write the shortlist back to the store
Canonical league mapping comes from the store's reference table, not hard-code.
Human notes come later — the recruitment_status table is defined but untouched.

Usage:
  python store_pipeline.py fotmob_player_seasons.csv
Then the store (dumbarton.db) holds players, stats, coefficients and the
shortlist — ready for a UI to read.

Deps: numpy, pandas  (+ db.py, league_equivalency.py, equivalency_real.py)
"""
from __future__ import annotations
import sys
import numpy as np
import pandas as pd
import db
import league_equivalency as le
import equivalency_real as eqr

REF_MIN_APPS = 8


def canon(idmap, namemap, lid, name):
    if lid in idmap:
        return idmap[lid]
    return namemap.get(name, name)


def ingest_csv(conn, path):
    df = pd.read_csv(path)
    db.upsert_players(conn, df)
    db.upsert_stats(conn, df)
    return len(df)


def compute_equivalency(conn):
    stats = db.get_stats_df(conn)
    idmap, namemap, cupmap = db.league_maps(conn)
    stats["league_c"] = [canon(idmap, namemap, i, n)
                         for i, n in zip(stats.league_id, stats.league_name)]
    stats["is_cup2"] = [bool(cupmap.get(i, bool(c)))
                        for i, c in zip(stats.league_id, stats.is_cup)]
    stats = stats[(~stats.is_cup2) & (stats.appearances > 0)].copy()
    stats["season_yr"] = stats.season.astype(str).str[:4].astype(int)

    prim = eqr.primary_league_seasons(stats)
    movers = eqr.build_movers(prim)
    if movers.empty:
        print("  no qualifying movers yet — ingest more squads across leagues.")
        return prim, {}
    if len(movers) < 8 or le.ANCHOR not in set(movers.from_league) | set(movers.to_league):
        print(f"  thin evidence: only {len(movers)} movers — coefficients provisional.")
    coeff, _, _ = le.estimate_coefficients(movers)
    counts = pd.concat([movers.from_league, movers.to_league]).value_counts().to_dict()
    linked = eqr.connected_to_anchor(movers)
    db.save_coefficients(conn, coeff, counts, linked)
    return prim, coeff


def surface(conn, prim, coeff):
    if not coeff:
        return pd.DataFrame()
    prim = prim.copy()
    prim["coeff"] = prim.league_c.map(coeff)
    prim = prim.dropna(subset=["coeff"])
    prim["adj_per_app"] = prim.per_app * prim.coeff
    cur = prim.loc[prim.groupby("player_id")["season_yr"].idxmax()].copy()
    if "position" in cur:                       # V1 scope: strikers only
        cur = cur[cur.position.astype(str).str.contains("Attack", case=False, na=False)]

    sl2 = cur[(cur.league_c == "SL2") & (cur.appearances >= REF_MIN_APPS)]
    if len(sl2) < 5:
        print("  <5 SL2 strikers for a reference — surfaced list is provisional.")
        ref = np.sort(cur.adj_per_app.values)
        prof_apps = float(cur.appearances.median())
    else:
        ref = np.sort(sl2.adj_per_app.values)
        prof_apps = float(sl2.appearances.median())

    recs = []
    for _, r in cur.iterrows():
        pct = float(np.searchsorted(ref, r.adj_per_app, "right") / max(1, len(ref)))
        dur = min(1.0, r.appearances / prof_apps) if prof_apps else 1.0
        fit = pct * dur
        fl = []
        if r.appearances < 10:
            fl.append("small sample")
        if r.coeff <= 0.7:
            fl.append("big translation")
        fl.append("avail/afford: needs TM layer")
        recs.append(dict(
            player_id=int(r.player_id), name=r.get("player_name"),
            league=r.league_c, season=str(r.season_yr),
            adj_per_app=round(float(r.adj_per_app), 3), appearances=int(r.appearances),
            fit=round(fit, 3), score=round(fit, 3), flags=", ".join(fl)))
    sl = pd.DataFrame(recs).sort_values("score", ascending=False).reset_index(drop=True)
    db.save_shortlist(conn, sl)
    return sl


def main(csv):
    conn = db.connect(); db.init_db(conn)
    n = ingest_csv(conn, csv)
    print(f"ingested {n} stat rows into the store ({db.DB_PATH})")

    prim, coeff = compute_equivalency(conn)
    print("\ncoefficients in the store:")
    print(db.get_coefficients(conn).to_string(index=False))

    sl = surface(conn, prim, coeff)
    if sl.empty:
        print("\nnothing surfaced yet — need more data (see notes above).")
        return
    print(f"\nsurfaced {len(sl)} strikers — top 12 read back from the store:\n")
    print(db.get_shortlist(conn).head(12)[
        ["name", "league", "adj_per_app", "appearances", "fit", "score", "flags"]
    ].to_string(index=False))
    print("\nStore now holds: players, stats, coefficients, shortlist. "
          "recruitment_status (human) stays empty until we build that layer.")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "fotmob_player_seasons.csv")
