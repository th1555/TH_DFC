#!/usr/bin/env python3
"""
store_pipeline.py  —  run the recruitment flow through the store
================================================================
CSV -> SQLite store -> league-equivalency coefficients -> surfaced shortlist.
Reuses the validated estimator (league_equivalency / equivalency_real). The
shortlist it writes now carries the fields a scouting UI needs: club, position,
age, raw vs SL2-adjusted output, goals, assists, flags.

Usage:  python store_pipeline.py fotmob_player_seasons.csv
"""
from __future__ import annotations
import sys
import numpy as np
import pandas as pd
import db
import league_equivalency as le
import equivalency_real as eqr

REF_MIN_APPS = 8
MIN_MOVERS = 5        # publish a coefficient only with this many movers
MIN_SAMPLE = 10       # appearances for a season to count as representative
FWD = r"forward|strik|attack|wing"   # forwards: striker/forward/winger/att-mid


def canon(idmap, namemap, lid, name):
    return idmap.get(lid) or namemap.get(name, name)


def ingest_csv(conn, path):
    df = pd.read_csv(path)
    db.upsert_players(conn, df)
    db.upsert_stats(conn, df)
    return len(df)


def prepare_stats(conn):
    stats = db.get_stats_df(conn)
    idmap, namemap, cupmap = db.league_maps(conn)
    stats["league_c"] = [canon(idmap, namemap, i, n)
                         for i, n in zip(stats.league_id, stats.league_name)]
    stats["is_cup2"] = [bool(cupmap.get(i, bool(c))) or ("cup" in str(n).lower())
                        for i, c, n in zip(stats.league_id, stats.is_cup, stats.league_name)]
    stats = stats[(~stats.is_cup2) & (stats.appearances > 0)].copy()
    stats["season_yr"] = stats.season.astype(str).str[:4].astype(int)
    return stats


def compute_equivalency(conn, stats):
    prim = eqr.primary_league_seasons(stats)
    movers = eqr.build_movers(prim)
    if movers.empty:
        print("  no qualifying movers yet — ingest more squads across leagues.")
        return {}
    if len(movers) < 8 or le.ANCHOR not in set(movers.from_league) | set(movers.to_league):
        print(f"  thin evidence: only {len(movers)} movers — coefficients provisional.")
    coeff, _, _ = le.estimate_coefficients(movers)
    counts = pd.concat([movers.from_league, movers.to_league]).value_counts().to_dict()
    linked = eqr.connected_to_anchor(movers)
    coeff = {l: c for l, c in coeff.items()
             if l == le.ANCHOR or counts.get(l, 0) >= MIN_MOVERS}
    db.save_coefficients(conn, coeff, counts, linked)
    return coeff


def surface(conn, stats, coeff):
    if not coeff:
        return pd.DataFrame()
    s = stats.copy()
    s["coeff"] = s.league_c.map(coeff)
    s = s.dropna(subset=["coeff"])
    s["adj_per_app"] = s.per_app * s.coeff

    # one row per player-season (primary league), then the representative season
    prim = s.loc[s.groupby(["player_id", "season_yr"]).appearances.idxmax()]
    idxs = []
    for _, g in prim.groupby("player_id"):
        recent = g[g.appearances >= MIN_SAMPLE]
        idxs.append(recent.season_yr.idxmax() if len(recent) else g.appearances.idxmax())
    cur = prim.loc[idxs].copy()

    if "position" in cur:
        print("  position labels in pool:",
              dict(cur.position.astype(str).value_counts().head(12)))
        cur = cur[cur.position.astype(str).str.contains(FWD, case=False, na=False)]
        print(f"  forwards matched: {len(cur)}")

    sl2 = cur[(cur.league_c == le.ANCHOR) & (cur.appearances >= REF_MIN_APPS)]
    if len(sl2) < 5:
        print("  <5 SL2 forwards for a reference — surfaced list is provisional.")
        ref = np.sort(cur.adj_per_app.values); prof_apps = float(cur.appearances.median())
    else:
        ref = np.sort(sl2.adj_per_app.values); prof_apps = float(sl2.appearances.median())

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
        if str(r.get("transfer_type")) in ("free transfer", "end of loan", "back from loan"):
            fl.append(str(r.transfer_type))
        fl.append("avail/afford: needs TM layer")
        recs.append(dict(
            player_id=int(r.player_id), name=r.get("player_name"),
            club=r.get("team"), league=r.league_c, position=r.get("position"),
            age=None if pd.isna(r.get("age")) else int(r.age),
            season=str(r.season_yr),
            raw_per_app=round(float(r.per_app), 3),
            adj_per_app=round(float(r.adj_per_app), 3),
            appearances=int(r.appearances),
            goals=int(r.goals), assists=int(r.assists),
            coeff=round(float(r.coeff), 3),
            fit=round(fit, 3), score=round(fit, 3), flags=", ".join(fl)))
    sl = pd.DataFrame(recs).sort_values("score", ascending=False).reset_index(drop=True)
    db.save_shortlist(conn, sl)
    return sl


def main(csv):
    conn = db.connect(); db.init_db(conn)
    n = ingest_csv(conn, csv)
    print(f"ingested {n} stat rows into the store ({db.DB_PATH})")

    stats = prepare_stats(conn)
    coeff = compute_equivalency(conn, stats)
    print("\ncoefficients in the store:")
    print(db.get_coefficients(conn).to_string(index=False))

    sl = surface(conn, stats, coeff)
    if sl.empty:
        print("\nnothing surfaced yet — need more data.")
        return
    print(f"\nsurfaced {len(sl)} forwards — top 12:\n")
    print(sl.head(12)[["name", "club", "league", "position", "age",
                       "adj_per_app", "appearances", "goals", "assists",
                       "score", "flags"]].to_string(index=False))
    print("\nStore holds players, stats, coefficients, shortlist. "
          "Run the app to explore it.")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "fotmob_player_seasons.csv")
