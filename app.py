#!/usr/bin/env python3
"""
app.py  —  Dumbarton FC recruitment shortlist (read-only Streamlit UI)
=====================================================================
Reads the SQLite store (dumbarton.db) and shows the surfaced striker shortlist
as a filterable table, each player expandable to the "why" behind the score,
plus the learned league exchange rates.

READ-ONLY by design. It never scrapes and never writes to the recruitment data
— which is exactly why it can live on Streamlit Cloud (a datacenter IP that the
data sources block). The scraping runs locally to build dumbarton.db; this app
just displays it.

If no real store is present (or it's empty), it builds a small DEMO store so the
interface renders immediately — clearly flagged, so you never mistake it for real
players.

Run locally:   streamlit run app.py
Deploy:        push app.py + dumbarton.db + requirements.txt to a repo, point
               Streamlit Cloud at it.
"""
import os
import sqlite3
import tempfile
import pandas as pd
import streamlit as st

DB_PATH = os.environ.get("DUMBARTON_DB", "dumbarton.db")
DEMO_PATH = os.path.join(tempfile.gettempdir(), "dumbarton_demo.db")


# ---------------------------------------------------------------------------
# data access (kept free of st.* so it's unit-testable without a browser)
# ---------------------------------------------------------------------------
def db_has_shortlist(path: str) -> bool:
    if not os.path.exists(path):
        return False
    try:
        conn = sqlite3.connect(path)
        n = conn.execute("SELECT COUNT(*) FROM shortlist").fetchone()[0]
        conn.close()
        return n > 0
    except Exception:
        return False


def build_demo_db(path: str):
    """A tiny, clearly-labelled demo store so the UI renders before real data."""
    conn = sqlite3.connect(path)
    conn.executescript("""
        DROP TABLE IF EXISTS shortlist;
        DROP TABLE IF EXISTS league_coefficients;
        DROP TABLE IF EXISTS player_season_stats;
        CREATE TABLE shortlist (player_id INTEGER, name TEXT, league TEXT, season TEXT,
          adj_per_app REAL, appearances INTEGER, fit REAL, score REAL, flags TEXT);
        CREATE TABLE league_coefficients (canonical TEXT, coeff_to_sl2 REAL,
          n_movers INTEGER, linked INTEGER);
        CREATE TABLE player_season_stats (player_id INTEGER, season TEXT,
          league_name TEXT, appearances INTEGER, goals INTEGER, assists INTEGER,
          per_app REAL);
    """)
    coeffs = [("NonLeague", 0.58, 40, 1), ("Lowland", 0.66, 60, 1),
              ("Highland", 0.70, 55, 1), ("SL2", 1.00, 120, 1),
              ("LOI", 1.09, 30, 1), ("League One", 1.26, 90, 1),
              ("Championship", 1.63, 45, 1)]
    conn.executemany("INSERT INTO league_coefficients VALUES (?,?,?,?)", coeffs)

    demo = [
        (1, "DEMO — A. Scorer",   "SL2",          "2025", 0.74, 34, 0.98, 0.98, "-"),
        (2, "DEMO — B. Poacher",  "League One",   "2025", 0.71, 30, 0.95, 0.95, "-"),
        (3, "DEMO — C. Target",   "Championship", "2025", 0.68, 22, 0.93, 0.93, "small sample"),
        (4, "DEMO — D. Winger",   "Highland",     "2025", 0.66, 33, 0.90, 0.90, "big translation"),
        (5, "DEMO — E. Forward",  "SL2",          "2025", 0.61, 31, 0.88, 0.88, "-"),
        (6, "DEMO — F. Striker",  "Lowland",      "2025", 0.59, 28, 0.84, 0.84, "big translation"),
        (7, "DEMO — G. Number9",  "SL2",          "2025", 0.55, 26, 0.80, 0.80, "-"),
        (8, "DEMO — H. Prospect", "League One",   "2025",  0.52, 9, 0.72, 0.72, "small sample"),
    ]
    conn.executemany("INSERT INTO shortlist VALUES (?,?,?,?,?,?,?,?,?)", demo)

    hist = []
    for pid, name, lg, season, adj, apps, *_ in demo:
        raw = round(adj / dict(c[:2] for c in coeffs).get(lg, 1.0), 2)
        goals = int(raw * apps * 0.6); assists = int(raw * apps) - goals
        hist.append((pid, season, lg, apps, goals, assists, raw))
        hist.append((pid, "2024", lg, max(5, apps - 6), max(0, goals - 2),
                     max(0, assists - 1), round(raw * 0.9, 2)))
    conn.executemany("INSERT INTO player_season_stats VALUES (?,?,?,?,?,?,?)", hist)
    conn.commit(); conn.close()


def load_tables(path: str, _mtime: float):
    conn = sqlite3.connect(path)
    sl = pd.read_sql("SELECT * FROM shortlist ORDER BY score DESC", conn)
    co = pd.read_sql("SELECT * FROM league_coefficients ORDER BY coeff_to_sl2", conn)
    conn.close()
    return sl, co


def player_history(path: str, _mtime: float, pid: int) -> pd.DataFrame:
    conn = sqlite3.connect(path)
    df = pd.read_sql(
        "SELECT season, league_name AS league, appearances, goals, assists, per_app "
        "FROM player_season_stats WHERE player_id=? ORDER BY season DESC",
        conn, params=(int(pid),))
    conn.close()
    return df


# cache wrappers (bust when the db file changes on disk)
_load = st.cache_data(load_tables)
_hist = st.cache_data(player_history)


# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------
def main():
    st.set_page_config(page_title="Dumbarton FC — recruitment", layout="wide")
    st.title("Dumbarton FC — striker shortlist")
    st.caption("Players ranked by SL2-equivalent output. A prioritisation aid — "
               "a person makes every call.")
    st.info("**Prototype on free data — a coverage filter, not a fine-grained "
            "verdict.** It surfaces who's worth watching; full player evaluation "
            "(xG, shot quality, style) needs paid event data like Wyscout/Opta.",
            icon="ℹ️")

    demo = not db_has_shortlist(DB_PATH)
    if demo:
        build_demo_db(DEMO_PATH)
        path = DEMO_PATH
        st.warning("Showing **demo data** — run `store_pipeline.py` locally to "
                   "build a real `dumbarton.db`, then redeploy it. Nothing below "
                   "is a real player.", icon="⚠️")
    else:
        path = DB_PATH

    mtime = os.path.getmtime(path)
    sl, co = _load(path, mtime)

    with st.sidebar:
        st.header("Filters")
        leagues = sorted(sl.league.dropna().unique())
        pick_lg = st.multiselect("League", leagues, default=leagues)
        max_apps = int(sl.appearances.max()) if len(sl) else 40
        min_apps = st.slider("Minimum appearances", 0, max_apps, 0)
        q = st.text_input("Search name").strip().lower()
        st.divider()
        st.caption("Read-only view. Availability & affordability need the "
                   "Transfermarkt layer (not yet wired), so this ranks on FIT. "
                   "Read scores as directional bands, not a precise order.")

    view = sl[sl.league.isin(pick_lg) & (sl.appearances >= min_apps)]
    if q:
        view = view[view.name.str.lower().str.contains(q)]

    tab_list, tab_rates = st.tabs(["Shortlist", "League exchange rates"])

    with tab_list:
        st.subheader(f"{len(view)} players")
        st.dataframe(
            view[["name", "league", "adj_per_app", "appearances", "score", "flags"]],
            hide_index=True, use_container_width=True,
            column_config={
                "name": "Player",
                "league": "League",
                "adj_per_app": st.column_config.NumberColumn("SL2-adj output/app", format="%.2f"),
                "appearances": "Apps",
                "score": st.column_config.ProgressColumn("Score", min_value=0, max_value=1, format="%.2f"),
                "flags": "Flags",
            })

        st.divider()
        st.subheader("Inspect a player")
        if len(view):
            who = st.selectbox("Player", view.name.tolist())
            row = view[view.name == who].iloc[0]
            c1, c2, c3 = st.columns(3)
            c1.metric("Shortlist score", f"{row.score:.2f}")
            c2.metric("SL2-adj output/app", f"{row.adj_per_app:.2f}")
            c3.metric("Appearances", int(row.appearances))
            if row.flags and row.flags != "-":
                st.info(f"Flags: {row.flags}")
            st.caption(f"Current league: {row.league}. The table below is this "
                       f"player's actual season-by-season record (raw, un-adjusted).")
            st.dataframe(_hist(path, mtime, int(row.player_id)),
                         hide_index=True, use_container_width=True)

    with tab_rates:
        st.subheader("Learned league exchange rates")
        st.caption("How output in each league translates to SL2. Below 1.0 = a "
                   "weaker league (numbers deflate); above 1.0 = stronger (inflate). "
                   "Learned only from players who moved between leagues.")
        st.bar_chart(co.set_index("canonical")["coeff_to_sl2"])
        st.dataframe(
            co.rename(columns={"canonical": "League", "coeff_to_sl2": "Coeff → SL2",
                               "n_movers": "Movers", "linked": "Linked to SL2"}),
            hide_index=True, use_container_width=True,
            column_config={"Coeff → SL2": st.column_config.NumberColumn(format="%.2f")})


if __name__ == "__main__":
    main()
