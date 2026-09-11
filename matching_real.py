#!/usr/bin/env python3
"""
Matching on REAL data  —  Dumbarton SL2 recruitment engine (shortlist layer)
============================================================================
Consumes `player_seasons_adjusted.csv` (from equivalency_real.py) and produces a
ranked striker shortlist by resemblance to proven SL2 output — on REAL FotMob
numbers, league-adjusted.

Scoring (a RANKING, so output is rewarded, not just "profile or bust"):
  fit = output_pctile  x  durability_factor  x  age_factor
    * output_pctile   — where the player's SL2-equivalent output/app ranks among
                        actual SL2 strikers (0..1). Higher output ranks higher.
    * durability      — appearances vs a real SL2 season, capped at 1 (low game
                        time drags you down; lots doesn't inflate you).
    * age_factor      — Gaussian around the profile age (only if age supplied).

Honest scope — the MARKET layer (age, value, availability, wages) is Transfermarkt's
job and isn't wired yet:
  * no market file  -> ranks on FIT only ("who resembles proven SL2 strikers?").
  * --market tm.csv (player_id,age,market_value,availability) -> folds in
    availability x affordability for the full shortlist score.

Usage:
  python matching_real.py
  python matching_real.py --market tm_market.csv
  python matching_real.py my_adjusted.csv --market tm.csv

Deps: numpy, pandas, matplotlib
"""
from __future__ import annotations
import sys
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ANCHOR = "SL2"
REF_MIN_APPS = 8           # min apps to count in the SL2 reference distribution
BUDGET_WEEKLY = 900
FEAS = {"free-agent": 1.0, "expiring": 0.7, "loan-candidate": 0.6, "contracted": 0.0}


def latest_season(df):
    return df.loc[df.groupby("player_id")["season_yr"].idxmax()].copy()


def afford(row):
    est = 250 + row.get("market_value", 0) / 4000 + max(0, row.get("age", 25) - 30) * 40
    if str(row.get("availability")) == "free-agent":
        est *= 0.9
    fit = 1.0 if est <= BUDGET_WEEKLY else float(np.exp(-(est - BUDGET_WEEKLY) / 400))
    return fit, int(est)


def run(adj_path, market_path=None):
    df = pd.read_csv(adj_path)
    if "position" in df:                        # V1 scope: strikers only
        df = df[df.position.astype(str).str.contains("Attack", case=False, na=False)]
    cur = latest_season(df)

    has_market = False
    if market_path:
        cur = cur.merge(pd.read_csv(market_path), on="player_id", how="left")
        has_market = ("market_value" in cur) or ("availability" in cur)
    has_age = "age" in cur.columns

    # --- build the SL2 reference from real proven strikers ---
    sl2 = cur[(cur.league_c == ANCHOR) & (cur.appearances >= REF_MIN_APPS)]
    if len(sl2) < 5:
        print("Not enough SL2 strikers to form a reference yet. Ingest more SL2 "
              "squads/seasons and re-run. (Data-volume step, not a code issue.)")
        return
    ref = np.sort(sl2.adj_per_app.values)             # output reference distribution
    prof_apps = float(sl2.appearances.median())
    if has_age:
        young = sl2[sl2.age <= 29]
        prof_age = float(young.age.mean() if len(young) else sl2.age.mean())
        age_sd = float(sl2.age.std() or 3.0)

    def fit_of(r):
        out_pct = float(np.searchsorted(ref, r.adj_per_app, "right") / len(ref))
        dur = min(1.0, r.appearances / prof_apps) if prof_apps else 1.0
        if has_age and not pd.isna(r.get("age", np.nan)):
            agef = float(np.exp(-0.5 * ((r.age - prof_age) / age_sd) ** 2))
        else:
            agef = 1.0
        return out_pct * dur * agef

    recs = []
    for _, r in cur.iterrows():
        fit = fit_of(r)
        fl = []
        if r.appearances < 10:
            fl.append("small sample")
        if r.get("coeff", 1.0) <= 0.7:
            fl.append("big translation")
        if has_market:
            feas = FEAS.get(str(r.get("availability")), 0.5)
            aff, wage = afford(r)
            if r.get("availability") == "loan-candidate":
                fl.append("loan")
            score = fit * feas * aff
        else:
            fl.append("avail/afford: needs TM layer")
            score = fit
        recs.append(dict(
            player=r.get("player_name", f"P{int(r.player_id)}"),
            league=r.league_c, adj=round(r.adj_per_app, 2), apps=int(r.appearances),
            fit=round(fit, 3), score=round(score, 3), flags=", ".join(fl) or "-"))

    sl = (pd.DataFrame(recs).sort_values("score", ascending=False)
          .head(15).reset_index(drop=True))

    print(f"strikers scored: {len(cur)} | SL2 reference: {len(sl2)} strikers | "
          f"median adj/app {np.median(ref):.2f}, median apps {prof_apps:.0f}"
          + (f", profile age {prof_age:.0f}" if has_age else ""))
    print("\nRANKED STRIKER SHORTLIST "
          + ("(full score)\n" if has_market else "(fit only — no market layer)\n"))
    print(sl.to_string(index=False))
    sl.to_csv("shortlist_real.csv", index=False)

    plt.style.use("seaborn-v0_8-whitegrid")
    fig, ax = plt.subplots(figsize=(9, 6))
    y = list(range(len(sl)))[::-1]
    ax.barh(y, sl.score, color="#c8102e")
    for yi, (_, r) in zip(y, sl.iterrows()):
        ax.text(r.score + 0.005, yi, f"adj {r.adj}  {r.league}", va="center", fontsize=8)
    ax.set_yticks(y); ax.set_yticklabels(sl.player)
    ax.set_xlabel("Shortlist score"); ax.set_xlim(0, max(sl.score) * 1.25)
    ax.set_title("Strikers matching the proven-SL2 profile (real data)",
                 fontsize=13, fontweight="bold")
    plt.tight_layout(); plt.savefig("shortlist_real.png", dpi=130)
    print("saved chart -> shortlist_real.png")
    if not has_market:
        print("\nNote: FIT ranking only. Availability + affordability need the "
              "Transfermarkt market layer — supply --market tm.csv to fold them in.")


if __name__ == "__main__":
    args = list(sys.argv[1:])
    market = None
    if "--market" in args:
        i = args.index("--market"); market = args[i + 1]; del args[i:i + 2]
    run(args[0] if args else "player_seasons_adjusted.csv", market)
