#!/usr/bin/env python3
"""
Equivalency on REAL data  —  Dumbarton SL2 recruitment engine
=============================================================
Wires the real FotMob ingestion CSV (from ingest_fotmob.py) into the VALIDATED
league-equivalency estimator in league_equivalency.py. The estimator itself is
unchanged — the maths that recovered known league strengths on synthetic data
is exactly what runs here. Only the data plumbing is new:

  * parse the real schema (season strings like "2025/2026", per-appearance rate)
  * drop cups and thin seasons, pick each player's PRIMARY league per season
  * build the "movers" table the estimator consumes
  * anchor Scottish League Two (FotMob id 125) as SL2 = 1.0
  * report coefficients WITH the sample size behind each (honesty about trust)

Why per-appearance, not per-90: FotMob doesn't expose per-season minutes at this
level (confirmed by probing), so goal-contributions PER APPEARANCE is the honest
rate. Ratios are what the estimator uses, so the method is unchanged.

Usage:
  python equivalency_real.py                       # reads fotmob_player_seasons.csv
  python equivalency_real.py a.csv b.csv           # combine several ingest CSVs

Deps: numpy, pandas  (+ league_equivalency.py beside it)
"""
from __future__ import annotations
import sys
import numpy as np
import pandas as pd
import league_equivalency as le          # reuse the validated estimator

MIN_APPS = 5        # appearances needed on BOTH sides of a move to trust the rate
LOOKBACK = 6        # only use moves within the last N seasons (recency)

# Canonicalise FotMob competitions -> our league names. 125 = Scottish L2 = anchor.
# Extend as you ingest more leagues (ids print in the ingest CSV).
LEAGUE_ID_CANON = {125: "SL2", 124: "League One", 123: "Championship", 66: "Premiership"}
LEAGUE_NAME_CANON = {"League Two": "SL2"}


def canon_league(league_id, league_name):
    if league_id in LEAGUE_ID_CANON:
        return LEAGUE_ID_CANON[league_id]
    return LEAGUE_NAME_CANON.get(league_name, league_name)


def load(paths) -> pd.DataFrame:
    df = pd.concat([pd.read_csv(p) for p in paths], ignore_index=True)
    df = df[(~df.get("is_cup", False).astype(bool)) & (df.appearances > 0)].copy()
    df["league_c"] = [canon_league(i, n) for i, n in zip(df.league_id, df.league)]
    df["season_yr"] = df.season.astype(str).str[:4].astype(int)   # "2025/2026" -> 2025
    return df


def primary_league_seasons(df: pd.DataFrame) -> pd.DataFrame:
    """One row per player per season: their PRIMARY league (most appearances)
    and the per-appearance output rate there."""
    idx = df.groupby(["player_id", "season_yr"])["appearances"].idxmax()
    keep = ["player_id", "season_yr", "league_c", "per_app", "appearances"]
    for c in ("player_name", "position", "minutes"):   # carry through if present
        if c in df.columns:
            keep.append(c)
    prim = df.loc[idx, keep].copy()
    return prim.sort_values(["player_id", "season_yr"])


def build_movers(prim: pd.DataFrame) -> pd.DataFrame:
    """Consecutive-season league changes, with output on both sides."""
    latest = prim.season_yr.max()
    rows = []
    for _, g in prim.groupby("player_id"):
        g = g.sort_values("season_yr")
        for (_, a), (_, b) in zip(g.iloc[:-1].iterrows(), g.iloc[1:].iterrows()):
            if (b.season_yr == a.season_yr + 1 and a.league_c != b.league_c
                    and b.season_yr >= latest - LOOKBACK
                    and a.appearances >= MIN_APPS and b.appearances >= MIN_APPS
                    and a.per_app > 0 and b.per_app > 0):        # output both sides
                rows.append(dict(from_league=a.league_c, to_league=b.league_c,
                                 rate_from=a.per_app, rate_to=b.per_app,
                                 w=min(a.appearances, b.appearances)))
    return pd.DataFrame(rows)


def connected_to_anchor(movers: pd.DataFrame) -> set:
    """Which leagues are linked (directly or via chaining) to SL2 — only those
    have a meaningful coefficient."""
    adj = {}
    for _, m in movers.iterrows():
        adj.setdefault(m.from_league, set()).add(m.to_league)
        adj.setdefault(m.to_league, set()).add(m.from_league)
    seen, stack = set(), [le.ANCHOR]
    while stack:
        n = stack.pop()
        if n in seen:
            continue
        seen.add(n)
        stack += list(adj.get(n, []))
    return seen


def run(paths):
    df = load(paths)
    prim = primary_league_seasons(df)
    movers = build_movers(prim)
    print(f"loaded {len(df)} league rows | {prim.player_id.nunique()} players | "
          f"{len(prim)} player-seasons")
    print(f"qualifying movers (>= {MIN_APPS} apps + output both sides): {len(movers)}")

    if len(movers) < 8 or le.ANCHOR not in set(movers.from_league) | set(movers.to_league):
        print("\n!! Not enough evidence yet. The estimator needs players who MOVED "
              "between leagues — including to/from SL2 — with real output on both "
              "sides. Ingest more squads across SL2 + feeder leagues over several "
              "seasons, then re-run. (This is a data-volume step, not a code issue.)")
        if movers.empty:
            return
    coeff, est_e, leagues = le.estimate_coefficients(movers)
    linked = connected_to_anchor(movers)

    # sample size behind each league
    counts = (pd.concat([movers.from_league, movers.to_league])
              .value_counts().to_dict())
    print(f"\n{'league':<14}{'coeff->SL2':>11}{'movers':>8}{'linked?':>9}")
    print("-" * 42)
    for l in sorted(coeff, key=lambda k: coeff[k]):
        link = "yes" if l in linked else "NO (unanchored)"
        n = "-" if l == le.ANCHOR else counts.get(l, 0)
        print(f"{l:<14}{coeff[l]:>11.2f}{str(n):>8}{link:>9}")
    print("-" * 42)
    print("coeff<1 = weaker league (output deflates to SL2); >1 = stronger (inflates)")
    print("trust the ones with more movers; thin/unanchored rows are provisional.")

    # apply and save league-adjusted output for every player-season
    prim["coeff"] = prim.league_c.map(coeff)
    prim["adj_per_app"] = prim.per_app * prim.coeff
    prim.to_csv("player_seasons_adjusted.csv", index=False)
    print(f"\nwrote league-adjusted player-seasons -> player_seasons_adjusted.csv")


if __name__ == "__main__":
    paths = sys.argv[1:] or ["fotmob_player_seasons.csv"]
    run(paths)
