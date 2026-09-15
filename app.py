#!/usr/bin/env python3
"""
app.py  —  Dumbarton FC recruitment dashboard (branded, adjustable, read-only)
==============================================================================
Scouting view over the SQLite store. Club-branded, with LIVE adjustable scoring
weights (the ranking recomputes in-browser as you drag sliders — no pipeline
re-run). Read-only: never scrapes. Demo-data fallback if no real store present.

Branding: also ship .streamlit/config.toml (provided separately) for the base
theme. Drop a crest.png beside this file to show the badge in the header.

Run:  streamlit run app.py
"""
import os
import sqlite3
import tempfile
import numpy as np
import pandas as pd
import streamlit as st

DB_PATH = os.environ.get("DUMBARTON_DB", "dumbarton.db")
DEMO_PATH = os.path.join(tempfile.gettempdir(), "dumbarton_demo.db")
GOLD, BLACK = "#F2A900", "#0a0a0a"

# recommended default weights (the "reset" target)
DEFAULTS = dict(w_out=70, w_dur=30, w_age=0, age_dir="Prefer younger",
                penalise=False, max_age=40)


# ---------------------------------------------------------------------------
# data access (no st.* — unit-testable)
# ---------------------------------------------------------------------------
def db_ready(path):
    if not os.path.exists(path):
        return False
    try:
        conn = sqlite3.connect(path)
        n = conn.execute("SELECT COUNT(*) FROM shortlist").fetchone()[0]
        conn.close()
        return n > 0
    except Exception:
        return False


def load(path, _mtime):
    conn = sqlite3.connect(path)
    sl = pd.read_sql("SELECT * FROM shortlist", conn)
    co = pd.read_sql("SELECT * FROM league_coefficients ORDER BY coeff_to_sl2", conn)
    conn.close()
    return sl, co


def history(path, _mtime, pid):
    conn = sqlite3.connect(path)
    df = pd.read_sql(
        "SELECT season, team AS club, league_name AS league, appearances, goals, "
        "assists, minutes, per_app, transfer_type FROM player_season_stats "
        "WHERE player_id=? AND (is_cup IS NULL OR is_cup=0) ORDER BY season DESC",
        conn, params=(int(pid),))
    conn.close()
    return df


def compute_scores(df, ref, target_apps, w_out, w_dur, w_age, age_dir, penalise):
    """Live weighted score from stored components. Each component is 0..1."""
    ref = np.sort(ref) if len(ref) else np.array([0.0])
    out = np.searchsorted(ref, df.adj_per_app.values, "right") / max(1, len(ref))
    dur = np.minimum(1.0, df.appearances.values / max(1, target_apps))
    comps = [(w_out, out), (w_dur, dur)]
    if w_age > 0 and "age" in df and df.age.notna().any():
        a = df.age.astype(float)
        span = max(1.0, (a.max() - a.min()))
        norm = (a - a.min()) / span
        agescore = (1 - norm) if age_dir == "Prefer younger" else norm
        comps.append((w_age, agescore.fillna(0.5).values))
    wsum = sum(w for w, _ in comps) or 1
    score = sum(w * c for w, c in comps) / wsum
    if penalise and "coeff" in df:
        score = score * np.where(df.coeff.values <= 0.7, 0.85, 1.0)
    return np.round(score, 3)


# ---------------------------------------------------------------------------
# demo store (matches the real schema)
# ---------------------------------------------------------------------------
def build_demo_db(path):
    conn = sqlite3.connect(path)
    conn.executescript("""
        DROP TABLE IF EXISTS shortlist; DROP TABLE IF EXISTS league_coefficients;
        DROP TABLE IF EXISTS player_season_stats;
        CREATE TABLE league_coefficients (canonical TEXT, coeff_to_sl2 REAL,
          n_movers INTEGER, linked INTEGER);
        CREATE TABLE player_season_stats (player_id INTEGER, season TEXT, team TEXT,
          league_name TEXT, appearances INTEGER, goals INTEGER, assists INTEGER,
          minutes INTEGER, per_app REAL, is_cup INTEGER, transfer_type TEXT);
    """)
    coeffs = [("Highland / Lowland", 0.67, 13, 1), ("SL2", 1.00, 99, 1),
              ("League One", 1.32, 92, 1), ("Championship", 1.41, 32, 1),
              ("Premiership", 2.54, 7, 1)]
    conn.executemany("INSERT INTO league_coefficients VALUES (?,?,?,?)", coeffs)
    cmap = {c[0]: c[1] for c in coeffs}
    demo = [
        (1, "DEMO — A. Scorer",  "Demo Rovers",   "SL2",                "Striker",           27, 0.73, 30, 14, 8),
        (2, "DEMO — B. Poacher", "Demo City",     "League One",         "Striker",           24, 0.61, 33, 15, 5),
        (3, "DEMO — C. Riser",   "Demo Thistle",  "Highland / Lowland", "Centre-Forward",    22, 0.90, 32, 24, 6),
        (4, "DEMO — D. Winger",  "Demo United",   "SL2",                "Right Winger",      29, 0.48, 34,  6, 12),
        (5, "DEMO — E. Target",  "Demo Athletic", "Championship",       "Striker",           26, 0.55, 22, 10, 4),
        (6, "DEMO — F. Prospect","Demo Rangers",  "SL2",                "Attacking Midfield",21, 0.40, 12,  3, 4),
    ]
    rows = []
    for pid, name, club, lg, pos, age, adj, apps, g, a in demo:
        raw = round(adj / cmap.get(lg, 1.0), 3)
        flags = ("big translation, avail/afford: needs TM layer"
                 if cmap.get(lg, 1) < 0.8 else "avail/afford: needs TM layer")
        rows.append((pid, name, club, lg, pos, age, "2025", raw, adj, apps, g, a,
                     round(cmap.get(lg, 1.0), 3), round(min(1, adj / 0.73), 3),
                     round(min(1, adj / 0.73), 3), flags))
    cols = ["player_id", "name", "club", "league", "position", "age", "season",
            "raw_per_app", "adj_per_app", "appearances", "goals", "assists",
            "coeff", "fit", "score", "flags"]
    pd.DataFrame(rows, columns=cols).to_sql("shortlist", conn, if_exists="replace", index=False)
    hist = []
    for pid, name, club, lg, pos, age, adj, apps, g, a in demo:
        raw = round(adj / cmap.get(lg, 1.0), 2)
        hist.append((pid, "2025", club, lg, apps, g, a, apps * 80, raw, 0, "free transfer"))
        hist.append((pid, "2024", club, lg, max(6, apps - 8), max(0, g - 3),
                     max(0, a - 2), (apps - 8) * 78, round(raw * 0.9, 2), 0, None))
    conn.executemany("INSERT INTO player_season_stats VALUES (?,?,?,?,?,?,?,?,?,?,?)", hist)
    conn.commit(); conn.close()


# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------
def brand():
    st.markdown(f"""
        <style>
          #MainMenu, footer {{visibility:hidden;}}
          .block-container {{padding-top:1.2rem;}}
          .dfc-header {{background:{BLACK}; padding:14px 22px; border-radius:10px;
             border-left:7px solid {GOLD}; margin-bottom:14px; display:flex;
             align-items:center; gap:16px;}}
          .dfc-header h1 {{color:{GOLD}; margin:0; font-size:26px;
             letter-spacing:2px; font-weight:800;}}
          .dfc-header p {{color:#dcdcdc; margin:2px 0 0; font-size:13px;}}
          .stProgress > div > div > div {{background-color:{GOLD};}}
        </style>""", unsafe_allow_html=True)
    c = st.container()
    cols = c.columns([1, 12]) if os.path.exists("crest.png") else [None, c]
    if os.path.exists("crest.png"):
        cols[0].image("crest.png", width=54)
    (cols[1] if os.path.exists("crest.png") else c).markdown(
        '<div class="dfc-header"><div><h1>DUMBARTON FC · RECRUITMENT</h1>'
        '<p>Sons of the Rock — forward scouting</p></div></div>',
        unsafe_allow_html=True)


def main():
    st.set_page_config(page_title="Dumbarton FC — Recruitment",
                       page_icon="⚽", layout="wide")
    brand()
    for k, v in DEFAULTS.items():
        st.session_state.setdefault(k, v)

    st.info("**Prototype on free data — a coverage filter, not a fine-grained "
            "verdict.** Full evaluation (xG, shot quality, style) needs paid "
            "event data like Wyscout/Opta.", icon="ℹ️")

    demo = not db_ready(DB_PATH)
    path = DEMO_PATH if demo else DB_PATH
    if demo:
        build_demo_db(DEMO_PATH)
        st.warning("Showing **demo data** — run `store_pipeline.py` locally to "
                   "build a real `dumbarton.db`, then redeploy it.", icon="⚠️")
    mtime = os.path.getmtime(path)
    sl, co = load(path, mtime)
    has_age = "age" in sl.columns and sl.age.notna().any()

    # ---- sidebar: conditions + weights ----
    with st.sidebar:
        st.header("Search conditions")
        positions = sorted(sl.position.dropna().unique()) if "position" in sl else []
        pick_pos = st.multiselect("Position", positions, default=positions)
        leagues = sorted(sl.league.dropna().unique())
        pick_lg = st.multiselect("Source league", leagues, default=leagues)
        min_apps = st.slider("Minimum appearances", 0,
                             int(sl.appearances.max()) if len(sl) else 40, 0)
        exclude = st.text_input("Exclude club (e.g. Dumbarton)").strip().lower()
        q = st.text_input("Search name").strip().lower()

        st.divider()
        st.header("Scoring weights")
        st.caption("Tune the ranking to your judgement. Reset anchors it back to "
                   "the recommended balance.")
        st.button("Reset to recommended",
                  on_click=lambda: st.session_state.update(DEFAULTS))
        w_out = st.slider("Weight: output", 0, 100, key="w_out")
        w_dur = st.slider("Weight: durability (games played)", 0, 100, key="w_dur")
        if has_age:
            w_age = st.slider("Weight: age", 0, 100, key="w_age")
            age_dir = st.radio("Age preference", ["Prefer younger", "Prefer experience"],
                               key="age_dir", horizontal=True)
            max_age = st.slider("Max age", 16, 40, key="max_age")
        else:
            w_age, age_dir, max_age = 0, "Prefer younger", 99
            st.caption("Age weighting unlocks once age data is ingested (re-run "
                       "the ingest to populate it).")
        penalise = st.checkbox("Discount heavy weak-league adjustments",
                               key="penalise")
        st.divider()
        st.caption("Availability & affordability (contract, value, free-agent) "
                   "need the Transfermarkt layer — not wired yet. Scores are "
                   "directional bands, not a precise order.")

    # ---- apply filters ----
    view = sl.copy()
    if pick_pos:
        view = view[view.position.isin(pick_pos)]
    view = view[view.league.isin(pick_lg) & (view.appearances >= min_apps)]
    if has_age:
        view = view[view.age.isna() | (view.age <= max_age)]
    if exclude:
        view = view[~view.club.fillna("").str.lower().str.contains(exclude)]
    if q:
        view = view[view.name.str.lower().str.contains(q)]

    # ---- live re-score against the SL2 reference, then rank ----
    ref = sl[sl.league == "SL2"].adj_per_app.values
    target_apps = int(sl[sl.league == "SL2"].appearances.median()) if (sl.league == "SL2").any() else 30
    if len(view):
        view = view.assign(score=compute_scores(
            view, ref, target_apps, w_out, w_dur, w_age, age_dir, penalise))
        view = view.sort_values("score", ascending=False).reset_index(drop=True)

    tab_list, tab_rates = st.tabs(["Shortlist", "League exchange rates"])

    with tab_list:
        st.subheader(f"{len(view)} forwards")
        show = [c for c in ["name", "club", "league", "position", "age",
                            "adj_per_app", "raw_per_app", "appearances", "goals",
                            "assists", "score", "flags"] if c in view.columns]
        st.dataframe(
            view[show], hide_index=True, use_container_width=True,
            column_config={
                "name": "Player", "club": "Club", "league": "League",
                "position": "Position", "age": "Age",
                "adj_per_app": st.column_config.NumberColumn("SL2-adj G+A/app", format="%.2f"),
                "raw_per_app": st.column_config.NumberColumn("Raw G+A/app", format="%.2f"),
                "appearances": "Apps", "goals": "G", "assists": "A",
                "score": st.column_config.ProgressColumn("Score", min_value=0, max_value=1, format="%.2f"),
                "flags": "Flags"})
        st.download_button("Download this shortlist (CSV)",
                           view[show].to_csv(index=False), "shortlist.csv", "text/csv")

        st.divider(); st.subheader("Player profile")
        if len(view):
            who = st.selectbox("Select a player", view.name.tolist())
            r = view[view.name == who].iloc[0]
            t = st.columns(5)
            t[0].metric("Club", r.get("club") or "—")
            t[1].metric("Position", r.get("position") or "—")
            t[2].metric("Age", int(r.age) if has_age and pd.notna(r.get("age")) else "—")
            t[3].metric("Current league", r.get("league") or "—")
            t[4].metric("Score", f"{r.score:.2f}")
            m = st.columns(4)
            m[0].metric("SL2-adj G+A / app", f"{r.adj_per_app:.2f}")
            m[1].metric("Raw G+A / app", f"{r.raw_per_app:.2f}")
            m[2].metric("League coeff → SL2", f"{r.get('coeff', float('nan')):.2f}")
            m[3].metric("Apps (rep. season)", int(r.appearances))
            if r.get("flags") and r.flags != "-":
                st.info(f"Flags: {r.flags}")
            st.caption("Contract, market value & free-agent status: **pending "
                       "Transfermarkt layer.**")
            st.markdown("**Season-by-season history** (raw, un-adjusted)")
            st.dataframe(
                history(path, mtime, int(r.player_id)), hide_index=True,
                use_container_width=True,
                column_config={
                    "season": "Season", "club": "Club", "league": "League",
                    "appearances": "Apps", "goals": "G", "assists": "A", "minutes": "Mins",
                    "per_app": st.column_config.NumberColumn("G+A/app", format="%.2f"),
                    "transfer_type": "Move"})

    with tab_rates:
        st.subheader("Learned league exchange rates")
        st.caption("How output in each league translates to SL2. Below 1.0 = "
                   "weaker (deflates); above 1.0 = stronger (inflates). Learned "
                   "only from players who moved between leagues.")
        st.bar_chart(co.set_index("canonical")["coeff_to_sl2"])
        st.dataframe(co.rename(columns={
            "canonical": "League", "coeff_to_sl2": "Coeff → SL2",
            "n_movers": "Movers", "linked": "Linked to SL2"}),
            hide_index=True, use_container_width=True)


if __name__ == "__main__":
    main()
