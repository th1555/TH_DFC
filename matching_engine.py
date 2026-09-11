#!/usr/bin/env python3
"""
Matching engine  —  Dumbarton SL2 recruitment engine (shortlisting layer)
=========================================================================
Sits on top of league_equivalency.py. Takes the SL2-equivalent output numbers
from that engine and turns them into a ranked, human-in-the-loop SHORTLIST of
available players who resemble proven SL2 success — filtered for who you can
realistically get and afford. Strikers-only (V1 scope), synthetic data with a
clean seam where real FotMob+TM data drops in.

Pipeline (spec §6-8):
  1. league-adjust everyone           (from league_equivalency.py)
  2. define "proven SL2 success"       -> a target profile (centroid)
  3. build who's AVAILABLE             (free / expiring / loan candidate)
  4. score similarity to the profile   (output-dominant, shortfall-penalised)
  5. affordability filter              (wage proxy vs a small-club budget)
  6. shortlist_score = similarity x availability x affordability -> rank

Run:  python matching_engine.py     (keep league_equivalency.py beside it)
Deps: numpy, pandas, matplotlib
"""
from __future__ import annotations
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

import league_equivalency as le   # the layer underneath

RNG = np.random.default_rng(7)
CURRENT_SEASON = 2024
BUDGET_WEEKLY = 900          # notional SL2 wage ceiling (£/week) — a proxy
TIER_RANK = {"Championship": 4, "League One": 3, "SL2": 2, "LOI": 2,
             "Lowland": 1, "Highland": 1, "NonLeague": 0}


# ---------------------------------------------------------------------------
# 1. Build a "current" player table with the fields TM/FotMob will supply
# ---------------------------------------------------------------------------
def build_current_table() -> pd.DataFrame:
    """Run the equivalency engine, then enrich each player's CURRENT season with
    age / market value / availability — the market layer TM provides for real."""
    seasons = le.make_player_seasons()
    coeff, _, _ = le.estimate_coefficients(le.find_movers(seasons))
    seasons = le.apply_translation(seasons, coeff)

    cur = seasons[seasons.season == CURRENT_SEASON].copy()
    cur["coeff"] = cur.league.map(coeff)

    ages, mvals, status, feas = [], [], [], []
    for _, r in cur.iterrows():
        age = int(np.clip(RNG.normal(25, 4), 17, 35))
        tier = TIER_RANK[r.league]
        # market value rises with tier and output, falls with age past ~27
        mv = (r.league_adj_per90 * 250_000 + tier * 120_000) \
            * (1.0 - max(0, age - 27) * 0.06)
        mv = max(15_000, mv * float(RNG.lognormal(0, 0.25)))

        # availability pools (spec §7)
        u = RNG.random()
        young_buried = (age <= 21 and tier >= 3 and r.minutes < 1100)
        if young_buried:
            st, fs = "loan-candidate", 0.6
        elif u < 0.14:
            st, fs = "free-agent", 1.0
        elif u < 0.30:
            st, fs = "expiring", 0.7
        else:
            st, fs = "contracted", 0.0        # not realistically gettable
        ages.append(age); mvals.append(round(mv)); status.append(st); feas.append(fs)

    cur["age"] = ages
    cur["market_value"] = mvals
    cur["availability"] = status
    cur["avail_feasibility"] = feas
    return cur


# ---------------------------------------------------------------------------
# 2. Define "proven SL2 success" and the target profile
# ---------------------------------------------------------------------------
def success_profile(cur: pd.DataFrame):
    """Players who did it IN SL2: strong league-adjusted output, real minutes,
    not ancient. Their average feature vector is the profile to match against."""
    sl2 = cur[cur.league == "SL2"]
    thresh = sl2.league_adj_per90.quantile(0.70)
    cohort = sl2[(sl2.league_adj_per90 >= thresh) &
                 (sl2.minutes >= 1500) & (sl2.age <= 29)]
    feats = ["league_adj_per90", "age", "minutes"]
    mean = cohort[feats].mean()
    std = cohort[feats].std().replace(0, 1.0)
    return cohort, mean, std, feats


# ---------------------------------------------------------------------------
# 3. Similarity: output-dominant, only penalise falling SHORT of the profile
# ---------------------------------------------------------------------------
def similarity(row, mean, std, feats, w=(0.6, 0.25, 0.15)):
    out_z = (row.league_adj_per90 - mean.league_adj_per90) / std.league_adj_per90
    age_z = (row.age - mean.age) / std.age
    dur_z = (row.minutes - mean.minutes) / std.minutes
    # output & durability: exceeding the profile is fine, only shortfall hurts
    d_out = max(0.0, -out_z)
    d_dur = max(0.0, -dur_z)
    d_age = abs(age_z)                     # too old OR too young both count
    dist2 = w[0] * d_out**2 + w[1] * d_age**2 + w[2] * d_dur**2
    return float(np.exp(-0.5 * dist2))


# ---------------------------------------------------------------------------
# 4. Affordability proxy
# ---------------------------------------------------------------------------
def afford(row):
    tier = TIER_RANK[row.league]
    est_wage = 200 + tier * 180 + row.market_value / 4000 + max(0, row.age - 30) * 40
    if row.availability == "free-agent":
        est_wage *= 0.9                    # no fee, slight wage room
    fit = 1.0 if est_wage <= BUDGET_WEEKLY else np.exp(-(est_wage - BUDGET_WEEKLY) / 400)
    return float(fit), int(est_wage)


def flags(row, coeff_val):
    f = []
    if row.minutes < 900:
        f.append("small sample")
    if row.age >= 31:
        f.append("age risk")
    if coeff_val <= 0.7:
        f.append("big translation")
    if row.availability == "loan-candidate":
        f.append("loan")
    return ", ".join(f) or "-"


# ---------------------------------------------------------------------------
# Assemble the shortlist
# ---------------------------------------------------------------------------
def build_shortlist(cur, mean, std, feats, top=12):
    avail = cur[cur.avail_feasibility > 0].copy()
    recs = []
    for _, r in avail.iterrows():
        sim = similarity(r, mean, std, feats)
        aff, wage = afford(r)
        score = sim * r.avail_feasibility * aff
        recs.append(dict(
            player=f"P{int(r.player_id):04d}", league=r.league, age=int(r.age),
            raw90=round(r.per90_raw, 2), adj90=round(r.league_adj_per90, 2),
            availability=r.availability, est_wage=wage,
            similarity=round(sim, 2), afford=round(aff, 2),
            score=round(score, 3), flags=flags(r, r.coeff),
        ))
    sl = pd.DataFrame(recs).sort_values("score", ascending=False).head(top)
    return sl.reset_index(drop=True)


def plot_shortlist(sl, path="shortlist_top.png"):
    colours = {"free-agent": "#c8102e", "expiring": "#ef8a62",
               "loan-candidate": "#4d4d4d"}
    plt.style.use("seaborn-v0_8-whitegrid")
    fig, ax = plt.subplots(figsize=(9, 6))
    y = range(len(sl))[::-1]
    ax.barh(list(y), sl.score, color=[colours[a] for a in sl.availability])
    for yi, (_, r) in zip(y, sl.iterrows()):
        ax.text(r.score + 0.005, yi, f"adj {r.adj90}  {r.availability}",
                va="center", fontsize=8)
    ax.set_yticks(list(y)); ax.set_yticklabels(sl.player)
    ax.set_xlabel("Shortlist score  (similarity x availability x affordability)")
    ax.set_title("Top available strikers matching the proven-SL2 profile",
                 fontsize=13, fontweight="bold")
    ax.set_xlim(0, max(sl.score) * 1.25)
    plt.tight_layout(); plt.savefig(path, dpi=130)
    print(f"\nsaved shortlist chart -> {path}")


if __name__ == "__main__":
    print("=" * 70)
    print("MATCHING ENGINE  —  ranked SL2 striker shortlist (synthetic demo)")
    print("=" * 70)
    cur = build_current_table()
    cohort, mean, std, feats = success_profile(cur)
    print(f"\ncurrent-season players: {len(cur)}   "
          f"available pool: {(cur.avail_feasibility > 0).sum()}")
    print(f"proven-SL2 success cohort: {len(cohort)} players")
    print("target profile (the average successful SL2 striker):")
    print(f"   adj output/90 {mean.league_adj_per90:.2f} | "
          f"age {mean.age:.0f} | minutes {mean.minutes:.0f}")

    sl = build_shortlist(cur, mean, std, feats)
    print("\nRANKED SHORTLIST (top 12) — the human works this top-down:\n")
    cols = ["player", "league", "age", "raw90", "adj90", "availability",
            "est_wage", "similarity", "afford", "score", "flags"]
    print(sl[cols].to_string(index=False))
    plot_shortlist(sl)

    print("\nRead-out: note how league-adjustment reshuffles the board — a big")
    print("raw90 from a weak league (flagged 'big translation') is pushed down,")
    print("while realistic-availability players rise. Every row is a human's call.")
