#!/usr/bin/env python3
"""
League-equivalency engine  —  Dumbarton SL2 recruitment engine (core method)
============================================================================
Puts players from different-strength leagues on ONE common "SL2-equivalent"
output scale, learned only from players who MOVED between leagues — no advanced
data required. This is the analytical heart of the recruitment tool (§5 of the
spec). It runs here on SYNTHETIC data with a known ground truth, so you can see
the estimator actually recover the true league strengths before real data is
ever plugged in.

METHOD (honest version):
  Each league L has a hidden "scoring environment" e_L (higher = easier to rack
  up output). A player with latent ability a produces per-90 output ~ a * e_L.
  A player who moves A -> B, same ability, gives us:
        rate_B / rate_A  ~  e_B / e_A
  Take logs and every mover becomes a linear observation:
        log(rate_B) - log(rate_A)  ~  x_B - x_A     (x_L = log e_L)
  Stack all movers, fix SL2 at x=0 (the anchor), and solve one weighted
  least-squares for every league's x at once. This auto-handles "chaining"
  through intermediate leagues and pools all evidence jointly.
  Coefficient to translate any league to SL2:  c(L) = e_SL2 / e_L = 1 / e_L.
      league_adj_output = raw_per90 * c(player_league)

Run:  python league_equivalency.py
Deps: numpy, pandas, matplotlib
"""
from __future__ import annotations
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

RNG = np.random.default_rng(42)
ANCHOR = "SL2"

# ---- ground-truth scoring environments (HIDDEN from the estimator) ----------
# higher = easier to produce output there. SL2 = 1.0 by definition (the anchor).
TRUE_E = {
    "Championship": 0.55,   # strongest / hardest to score
    "League One":   0.75,
    "SL2":          1.00,   # anchor
    "LOI":          0.90,   # League of Ireland Premier
    "Highland":     1.45,
    "Lowland":      1.50,
    "NonLeague":    1.70,   # English lower non-league
}

# realistic transition edges we can actually observe movers on, with counts
TRANSITIONS = [
    ("Highland", "SL2", 70), ("SL2", "Highland", 25),
    ("Lowland", "SL2", 60), ("SL2", "Lowland", 20),
    ("SL2", "League One", 55), ("League One", "SL2", 45),
    ("League One", "Championship", 40), ("Championship", "League One", 35),
    ("NonLeague", "SL2", 40), ("NonLeague", "Lowland", 30),
    ("LOI", "SL2", 30), ("LOI", "League One", 25),
]

# When True, upward movers are positively SELECTED (only the better players get
# the move up) — the survivorship bias flagged in the spec. Shows how it warps
# the estimate and motivates the causal/DiD fix (spec §14).
SELECTION_BIAS = False


def _minutes():
    # a spread of playing time; some fringe, some regulars
    return float(np.clip(RNG.normal(1900, 700), 350, 3200))


def make_player_seasons() -> pd.DataFrame:
    """Synthetic player-seasons with embedded league moves. Returns the tidy
    schema the real FotMob+TM pipeline will also produce."""
    rows = []
    pid = 0
    tier_rank = {"Championship": 4, "League One": 3, "SL2": 2, "LOI": 2,
                 "Lowland": 1, "Highland": 1, "NonLeague": 0}
    for a_league, b_league, n in TRANSITIONS:
        for _ in range(n):
            pid += 1
            ability = float(RNG.gamma(shape=3.0, scale=0.12))  # latent talent
            # positive selection on upward moves, if enabled
            if SELECTION_BIAS and tier_rank[b_league] > tier_rank[a_league]:
                # resample ability upward: only the better ones move up
                ability = max(ability, float(RNG.gamma(4.5, 0.12)))
            for season, lg in [(2023, a_league), (2024, b_league)]:
                mins = _minutes()
                noise = float(RNG.lognormal(0, 0.18))
                per90 = ability * TRUE_E[lg] * noise        # goal contributions/90
                gc = per90 * mins / 90.0                     # total G+A
                rows.append(dict(
                    player_id=pid, season=season, league=lg,
                    position="ATT", minutes=round(mins),
                    goal_contribs=round(gc),
                    per90_raw=per90,
                ))
    return pd.DataFrame(rows)


def find_movers(df: pd.DataFrame, min_minutes: int = 600) -> pd.DataFrame:
    """Players observed in two consecutive seasons in DIFFERENT leagues, with
    enough minutes on both sides to trust the rate."""
    df = df[df.minutes >= min_minutes]
    out = []
    for pid, g in df.groupby("player_id"):
        g = g.sort_values("season")
        for (_, a), (_, b) in zip(g.iloc[:-1].iterrows(), g.iloc[1:].iterrows()):
            if a.league != b.league and b.season == a.season + 1:
                out.append(dict(
                    player_id=pid, from_league=a.league, to_league=b.league,
                    rate_from=a.per90_raw, rate_to=b.per90_raw,
                    w=min(a.minutes, b.minutes),
                ))
    return pd.DataFrame(out)


def estimate_coefficients(movers: pd.DataFrame):
    """Weighted least-squares for log(e_L), SL2 anchored to 0.
    Returns (coeff_to_sl2: dict, est_e: dict, leagues: list)."""
    leagues = sorted(set(movers.from_league) | set(movers.to_league))
    free = [l for l in leagues if l != ANCHOR]          # SL2 fixed at x=0
    idx = {l: i for i, l in enumerate(free)}

    A = np.zeros((len(movers), len(free)))
    y = np.log(movers.rate_to.values) - np.log(movers.rate_from.values)
    for r, (_, m) in enumerate(movers.iterrows()):
        if m.to_league != ANCHOR:
            A[r, idx[m.to_league]] += 1.0
        if m.from_league != ANCHOR:
            A[r, idx[m.from_league]] -= 1.0
    w = np.sqrt(movers.w.values)                        # WLS by min-minutes
    x, *_ = np.linalg.lstsq(A * w[:, None], y * w, rcond=None)

    est_e = {ANCHOR: 1.0}
    for l in free:
        est_e[l] = float(np.exp(x[idx[l]]))
    coeff = {l: 1.0 / e for l, e in est_e.items()}      # translate L -> SL2
    return coeff, est_e, leagues


def apply_translation(df: pd.DataFrame, coeff: dict) -> pd.DataFrame:
    df = df.copy()
    df["coeff_to_SL2"] = df.league.map(coeff)
    df["league_adj_per90"] = df.per90_raw * df["coeff_to_SL2"]
    return df


def report(coeff, est_e, movers):
    counts = (pd.concat([movers.from_league, movers.to_league])
              .value_counts().to_dict())
    print(f"\nMovers used: {len(movers)}  across {len(coeff)} leagues"
          f"   (selection_bias={SELECTION_BIAS})\n")
    print(f"{'league':<13}{'movers':>7}{'true e':>9}{'est e':>9}"
          f"{'true c':>9}{'est c':>9}{'err%':>8}")
    print("-" * 64)
    rows = []
    for l in sorted(coeff, key=lambda k: TRUE_E[k]):
        tc, ec = 1 / TRUE_E[l], coeff[l]
        err = 100 * (ec - tc) / tc
        rows.append((l, TRUE_E[l], est_e[l], tc, ec, err))
        n = "-" if l == ANCHOR else counts.get(l, 0)
        print(f"{l:<13}{str(n):>7}{TRUE_E[l]:>9.2f}{est_e[l]:>9.2f}"
              f"{tc:>9.2f}{ec:>9.2f}{err:>8.1f}")
    mae = np.mean([abs(r[4] - r[3]) for r in rows])
    print("-" * 64)
    print(f"mean abs error on coefficients: {mae:.3f}")
    return rows


def plot_validation(rows, path="equivalency_validation.png"):
    true_c = [r[3] for r in rows]
    est_c = [r[4] for r in rows]
    names = [r[0] for r in rows]
    plt.style.use("seaborn-v0_8-whitegrid")
    fig, ax = plt.subplots(figsize=(7, 7))
    lim = [0, max(true_c + est_c) * 1.15]
    ax.plot(lim, lim, "--", color="#999", lw=1, label="perfect recovery (y=x)")
    ax.scatter(true_c, est_c, s=90, color="#c8102e", zorder=3)  # Dumbarton-ish red
    for n, tc, ec in zip(names, true_c, est_c):
        ax.annotate(n, (tc, ec), xytext=(6, 4), textcoords="offset points",
                    fontsize=9)
    ax.set_xlim(lim); ax.set_ylim(lim)
    ax.set_title("Estimator recovers true league coefficients from movers alone",
                 fontsize=13, fontweight="bold")
    ax.set_xlabel("True coefficient to SL2", fontsize=11)
    ax.set_ylabel("Estimated coefficient to SL2", fontsize=11)
    ax.legend()
    plt.tight_layout()
    plt.savefig(path, dpi=130)
    print(f"\nsaved validation plot -> {path}")


if __name__ == "__main__":
    print("=" * 64)
    print("LEAGUE-EQUIVALENCY ENGINE  (synthetic ground-truth demo)")
    print("=" * 64)
    df = make_player_seasons()
    print(f"generated {len(df)} player-seasons, {df.player_id.nunique()} players")

    movers = find_movers(df)
    coeff, est_e, leagues = estimate_coefficients(movers)
    rows = report(coeff, est_e, movers)
    plot_validation(rows)

    adj = apply_translation(df, coeff)
    # show the payoff: same raw number is worth very different amounts by league
    print("\nWorked example — a striker posting 0.60 raw goal-contribs/90:")
    for lg in ["NonLeague", "Highland", "SL2", "League One", "Championship"]:
        print(f"  in {lg:<13} -> {0.60 * coeff[lg]:.2f} SL2-equivalent per90")
    print("\n(the same tally in the Championship is worth ~3x what it is in the "
          "Highland League once translated — which is the whole point.)")
