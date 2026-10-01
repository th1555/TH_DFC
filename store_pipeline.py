#!/usr/bin/env python3
"""
store_pipeline.py  —  run the recruitment flow through the store
================================================================
CSV -> SQLite store -> league-equivalency coefficients -> surfaced shortlist.

Evaluation (rebuilt): instead of rating a player on one season, it summarises
their recent CAREER on an SL2-equivalent scale, keeps identity (club/league/age)
CURRENT, and flags trajectory (a recent step up, and rising/steady/declining).
The app turns these into two live ratings: "best right now" and "best bet going
forward" (age- and trajectory-adjusted).
"""
from __future__ import annotations
import sys
import numpy as np
import pandas as pd
import db
import league_equivalency as le
import equivalency_real as eqr

MIN_MOVERS = 5           # publish a coefficient only with this many movers
FWD = r"forward|strik|attack|wing"
RECENCY = 0.55           # weight decay per season into the past
LOOKBACK = 4             # seasons of history to summarise
MEANINGFUL_APPS = 10     # a season needs this many games to count toward level
PEAK_APPS = 10           # same bar as a counted season, so best >= average
TREND_APPS = 12          # a season needs this many games to set the trend


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


def summarise_player(g, coeff):
    """g = one player's primary-league seasons, newest first, INCLUDING seasons
    in leagues with no exchange rate (coeff NaN). Identity comes from the newest
    row of all; the rating uses only rated seasons with a real sample."""
    latest = g.iloc[0]                                   # identity (current)
    rated = g.dropna(subset=["coeff"])
    good = rated[rated.appearances >= MEANINGFUL_APPS].head(LOOKBACK)
    if good.empty:
        return None
    latest_yr = int(good.season_yr.max())
    w = (RECENCY ** (latest_yr - good.season_yr)) * good.appearances
    level = float((good.adj * w).sum() / w.sum())        # SL2-equiv career level
    raw_level = float((good.per_app * w).sum() / w.sum())
    peakset = good[good.appearances >= PEAK_APPS]
    peakset = peakset if len(peakset) else good.loc[[good.appearances.idxmax()]]
    pk = peakset.loc[peakset.adj.idxmax()]
    # stepped up: the league he's in NOW is stronger than his last established one
    now_coeff = latest.coeff if pd.notna(latest.coeff) else None
    est = good[(good.league_c != latest.league_c) & (good.appearances >= 8)]
    stepped_up = int(now_coeff is not None and len(est) > 0
                     and now_coeff > est.iloc[0].coeff * 1.05)
    # trend: needs two full-ish seasons, else too early to tell
    full = good[good.appearances >= TREND_APPS]
    trend = "unknown"
    if len(full) >= 2:
        last, before = full.iloc[0], full.iloc[1:]
        bw = (RECENCY ** (int(last.season_yr) - before.season_yr)) * before.appearances
        prior = float((before.adj * bw).sum() / bw.sum())
        trend = "steady"
        if prior > 0 and last.adj >= prior * 1.15:
            trend = "rising"
        elif prior > 0 and last.adj <= prior * 0.85:
            trend = "declining"
    fl = []
    if int(good.appearances.sum()) < 20:
        fl.append("few games")
    if pk.coeff <= 0.7:
        fl.append("peak in a weaker league")
    cur_apps = int(latest.appearances)
    return dict(
        player_id=int(latest.player_id), name=latest.get("player_name"),
        club=latest.get("team"), league=latest.league_c,
        position=latest.get("position"),
        age=None if pd.isna(latest.get("age")) else int(latest.age),
        level=round(level, 3), raw_level=round(raw_level, 3),
        peak=round(float(pk.adj), 3), peak_season=str(pk.get("season")),
        peak_league=pk.league_c, peak_club=pk.get("team"),
        trend=trend, stepped_up=stepped_up,
        career_apps=int(good.appearances.sum()),
        career_goals=int(good.goals.sum()), career_assists=int(good.assists.sum()),
        seasons_rated=int(len(good)),
        cur_season=str(latest.get("season")), cur_apps=cur_apps,
        cur_goals=int(latest.goals), cur_assists=int(latest.assists),
        cur_counted=int(cur_apps >= MEANINGFUL_APPS and pd.notna(latest.coeff)),
        flags=", ".join(fl))


def surface(conn, stats, coeff):
    if not coeff:
        return pd.DataFrame()
    s = stats.copy()
    s["coeff"] = s.league_c.map(coeff)            # NaN = league with no rate yet
    s["adj"] = s.per_app * s.coeff
    prim = s.loc[s.groupby(["player_id", "season_yr"]).appearances.idxmax()]

    recs = []
    for _, g in prim.groupby("player_id"):
        rec = summarise_player(g.sort_values("season_yr", ascending=False), coeff)
        if rec:
            recs.append(rec)
    sl = pd.DataFrame(recs)
    if "position" in sl:
        print("  position labels in pool:",
              dict(sl.position.astype(str).value_counts().head(12)))
        sl = sl[sl.position.astype(str).str.contains(FWD, case=False, na=False)]
        print(f"  forwards matched: {len(sl)}")
    sl = sl.sort_values("level", ascending=False).reset_index(drop=True)
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
    print(f"\nsurfaced {len(sl)} forwards — top 12 by career level:\n")
    cols = ["name", "club", "league", "age", "level", "peak", "trend",
            "stepped_up", "career_apps", "career_goals", "flags"]
    print(sl.head(12)[[c for c in cols if c in sl.columns]].to_string(index=False))
    print("\nStore holds players, stats, coefficients, shortlist. Run the app.")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "fotmob_player_seasons.csv")
