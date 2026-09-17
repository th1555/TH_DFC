#!/usr/bin/env python3
"""
app.py — Dumbarton FC recruitment dashboard (plain-language, read-only)
======================================================================
Built to be clear to a non-technical user: every figure has a plain label and a
"?" explanation, the data source and last-updated date are shown up front, and
what you can do is stated simply. Read-only; never scrapes. Demo fallback if no
real store is present.
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


def plain_notes(flags):
    """Turn internal flags into plain words; drop the universal caveat."""
    if not flags:
        return ""
    out = []
    for p in [x.strip() for x in str(flags).split(",")]:
        if not p or p == "-" or "needs TM" in p:
            continue
        if p == "small sample":
            out.append("⚠ Few games — treat with caution")
        elif p == "big translation":
            out.append("↓ From a much weaker league (adjusted down)")
        elif p in ("free transfer", "end of loan", "back from loan"):
            out.append(f"• Recent move: {p}")
        else:
            out.append(p)
    return "  ·  ".join(out)


# ---------------------------------------------------------------------------
# demo store
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
                     round(min(1, adj / 0.73), 3), flags, "2026-01-01T00:00:00+00:00"))
    cols = ["player_id", "name", "club", "league", "position", "age", "season",
            "raw_per_app", "adj_per_app", "appearances", "goals", "assists",
            "coeff", "fit", "score", "flags", "computed_at"]
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
          html, body, [class*="css"] {{font-size:16px;}}
          .block-container {{padding-top:1.1rem;}}
          .dfc-header {{background:{BLACK}; padding:16px 24px; border-radius:10px;
             border-left:7px solid {GOLD}; margin-bottom:12px;}}
          .dfc-header h1 {{color:{GOLD}; margin:0; font-size:28px;
             letter-spacing:2px; font-weight:800;}}
          .dfc-header p {{color:#dcdcdc; margin:3px 0 0; font-size:14px;}}
          .stProgress > div > div > div {{background-color:{GOLD};}}
        </style>""", unsafe_allow_html=True)
    if os.path.exists("crest.png"):
        c1, c2 = st.columns([1, 13])
        c1.image("crest.png", width=56)
        holder = c2
    else:
        holder = st
    holder.markdown(
        '<div class="dfc-header"><h1>DUMBARTON FC · RECRUITMENT</h1>'
        '<p>Sons of the Rock — a tool to help find forward players</p></div>',
        unsafe_allow_html=True)


def main():
    st.set_page_config(page_title="Dumbarton FC — Recruitment",
                       page_icon="⚽", layout="wide")
    brand()
    for k, v in DEFAULTS.items():
        st.session_state.setdefault(k, v)

    demo = not db_ready(DB_PATH)
    path = DEMO_PATH if demo else DB_PATH
    if demo:
        build_demo_db(DEMO_PATH)
    mtime = os.path.getmtime(path)
    sl, co = load(path, mtime)
    has_age = "age" in sl.columns and sl.age.notna().any()
    updated = (str(sl.computed_at.max())[:10]
               if "computed_at" in sl.columns and len(sl) else "—")

    # ---- plain-language intro: what it is, where from, what you can do ----
    st.markdown(
        "#### What this is\n"
        "A tool that suggests **forward players who might suit Dumbarton**. It looks "
        "at each player's goals and assists, then **adjusts for how strong their "
        "league is**, so players from different leagues can be compared fairly. "
        "The players near the top are the ones **most worth watching** — it's a "
        "shortlist to guide you, **not a final decision**.")
    src = st.columns([3, 1])
    src[0].markdown(
        f"📊 **Where the numbers come from:** FotMob (public football statistics). "
        f"The rankings are worked out automatically by this tool — they are not "
        f"anyone's opinion.")
    src[1].markdown(f"🕓 **Data last updated:**\n\n{updated}")

    with st.expander("What this tool can and cannot do — please read", expanded=False):
        st.markdown(
            "**It can:** scan lots of players you'd never have time to watch, compare "
            "them fairly across leagues, and put the most promising forwards at the top.\n\n"
            "**A person still decides everything.** This is a guide, not a verdict.\n\n"
            "**It does *not* yet know** who is actually available, out of contract, or "
            "what wages they want — that information is coming in a later version.\n\n"
            "**It cannot judge** playing style, attitude, or fitness — that still needs "
            "your eyes (or paid video/data the club would need to buy).\n\n"
            "**What you can do here:** filter the list on the left, click any player to "
            "see their full history, download the list, and (advanced) change how the "
            "rating is weighted.")

    if demo:
        st.warning("This is **example data**, not real players — it's here to show how "
                   "the tool looks. Real player data is loaded separately.", icon="⚠️")

    # ---- sidebar: simple filters first, advanced tuning tucked away ----
    with st.sidebar:
        st.header("Narrow the list")
        positions = sorted(sl.position.dropna().unique()) if "position" in sl else []
        pick_pos = st.multiselect("Position", positions, default=positions,
                                  help="Which kinds of forward to include.")
        leagues = sorted(sl.league.dropna().unique())
        pick_lg = st.multiselect("League they play in", leagues, default=leagues,
                                 help="Limit to players from certain leagues.")
        min_apps = st.slider("Minimum games played", 0,
                             int(sl.appearances.max()) if len(sl) else 40, 0,
                             help="Hide players with very few games (small, unreliable samples).")
        exclude = st.text_input("Hide a club (e.g. Dumbarton)",
                                help="Type a club name to remove its players — "
                                     "e.g. your own, so you only see possible signings.").strip().lower()
        q = st.text_input("Search by name").strip().lower()

        with st.expander("⚙️ Advanced: change the rating (optional)"):
            st.caption("Only if you want to. These change how the 'Fit rating' is "
                       "worked out. 'Reset' puts them back to our recommended balance.")
            st.button("Reset to recommended",
                      on_click=lambda: st.session_state.update(DEFAULTS))
            w_out = st.slider("Value output (goals + assists)", 0, 100, key="w_out")
            w_dur = st.slider("Value games played", 0, 100, key="w_dur")
            if has_age:
                w_age = st.slider("Value age", 0, 100, key="w_age")
                age_dir = st.radio("Age preference",
                                   ["Prefer younger", "Prefer experience"],
                                   key="age_dir", horizontal=True)
                max_age = st.slider("Maximum age", 16, 40, key="max_age")
            else:
                w_age, age_dir, max_age = 0, "Prefer younger", 99
                st.caption("Age options appear once age data has been loaded.")
            penalise = st.checkbox("Be stricter on weaker-league players", key="penalise")

    # ---- filters ----
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

    # ---- score live, scale to 0–100, add plain notes ----
    ref = sl[sl.league == "SL2"].adj_per_app.values
    target_apps = int(sl[sl.league == "SL2"].appearances.median()) if (sl.league == "SL2").any() else 30
    if len(view):
        view = view.assign(score=compute_scores(
            view, ref, target_apps, w_out, w_dur, w_age, age_dir, penalise))
        view["rating"] = (view.score * 100).round().astype(int)
        view["notes"] = view.flags.apply(plain_notes)
        view = view.sort_values("rating", ascending=False).reset_index(drop=True)

    tab_list, tab_rates = st.tabs(["⭐ Recommended players", "📈 How leagues compare"])

    with tab_list:
        st.subheader(f"{len(view)} players match your filters")
        if len(view):
            st.caption("Where they play now:  " + "   ".join(
                f"**{k}** {v}" for k, v in view.league.value_counts().items()))
        cols = {
            "name": st.column_config.TextColumn("Player"),
            "club": st.column_config.TextColumn("Current club"),
            "league": st.column_config.TextColumn("League"),
            "position": st.column_config.TextColumn("Position"),
            "age": st.column_config.NumberColumn("Age"),
            "rating": st.column_config.ProgressColumn(
                "Fit rating", help="Our overall rating out of 100 of how well this "
                "player's output matches proven League Two forwards. Higher = more "
                "worth watching. A guide, not a verdict.", min_value=0, max_value=100, format="%d"),
            "adj_per_app": st.column_config.NumberColumn(
                "Adjusted G+A per game", help="Goals + assists per game, adjusted so "
                "players from stronger or weaker leagues compare fairly on a League "
                "Two scale.", format="%.2f"),
            "raw_per_app": st.column_config.NumberColumn(
                "Actual G+A per game", help="Their real goals + assists per game in "
                "their own league, before any adjustment.", format="%.2f"),
            "appearances": st.column_config.NumberColumn(
                "Games", help="Games played in the season being rated."),
            "goals": st.column_config.NumberColumn("Goals"),
            "assists": st.column_config.NumberColumn("Assists"),
            "notes": st.column_config.TextColumn(
                "Notes", help="Cautions specific to this player."),
        }
        order = ["name", "club", "league", "position", "age", "rating",
                 "adj_per_app", "raw_per_app", "appearances", "goals", "assists", "notes"]
        order = [c for c in order if c in view.columns]
        st.dataframe(view[order], hide_index=True, use_container_width=True,
                     column_config=cols)
        st.download_button("⬇️ Download this list (opens in Excel)",
                           view[order].to_csv(index=False), "shortlist.csv", "text/csv",
                           help="Save the list as a spreadsheet.")

        st.divider()
        st.subheader("See one player in detail")
        st.caption("Pick a player to see their season-by-season record.")
        if len(view):
            who = st.selectbox("Player", view.name.tolist(), label_visibility="collapsed")
            r = view[view.name == who].iloc[0]
            t = st.columns(5)
            t[0].metric("Current club", r.get("club") or "—")
            t[1].metric("Position", r.get("position") or "—")
            t[2].metric("Age", int(r.age) if has_age and pd.notna(r.get("age")) else "—")
            t[3].metric("League", r.get("league") or "—")
            t[4].metric("Fit rating", f"{int(r.rating)} / 100",
                        help="Overall rating out of 100 — a guide to who's worth watching.")
            m = st.columns(3)
            m[0].metric("Adjusted G+A / game", f"{r.adj_per_app:.2f}",
                        help="Adjusted to a League Two scale so leagues compare fairly.")
            m[1].metric("Actual G+A / game", f"{r.raw_per_app:.2f}",
                        help="Their real rate in their own league.")
            m[2].metric("Games (season rated)", int(r.appearances))
            note = plain_notes(r.get("flags"))
            if note:
                st.info(f"Notes: {note}")
            st.caption("We do **not** yet know this player's contract, wages, or whether "
                       "he's available — that comes in a later version.")
            st.markdown("**Season-by-season record** (their real numbers, not adjusted)")
            hcols = {
                "season": st.column_config.TextColumn("Season"),
                "club": st.column_config.TextColumn("Club"),
                "league": st.column_config.TextColumn("League"),
                "appearances": st.column_config.NumberColumn("Games"),
                "goals": st.column_config.NumberColumn("Goals"),
                "assists": st.column_config.NumberColumn("Assists"),
                "minutes": st.column_config.NumberColumn("Minutes"),
                "per_app": st.column_config.NumberColumn("G+A per game", format="%.2f"),
                "transfer_type": st.column_config.TextColumn("Move that summer"),
            }
            st.dataframe(history(path, mtime, int(r.player_id)), hide_index=True,
                         use_container_width=True, column_config=hcols)

    with tab_rates:
        st.subheader("How we compare different leagues")
        st.markdown(
            "Leagues are not equal — it's harder to score in the Championship than in "
            "the Highland League. So before comparing players, we **translate everyone's "
            "goals and assists onto a League Two scale.**\n\n"
            "- A number **below 1.0** means a **weaker** league — those players' output "
            "is **reduced** (e.g. Highland/Lowland).\n"
            "- A number **above 1.0** means a **stronger** league — those players' output "
            "is **boosted** (e.g. Championship).\n\n"
            "These are **not guesses** — they're worked out from players who **actually "
            "moved** between the leagues, and how their scoring changed. The **'players "
            "moved'** column shows how much evidence sits behind each figure.")
        st.bar_chart(co.set_index("canonical")["coeff_to_sl2"])
        rates = co.rename(columns={"canonical": "League",
                                   "coeff_to_sl2": "Adjustment vs League Two",
                                   "n_movers": "Players moved (evidence)",
                                   "linked": "linked"}).drop(columns=["linked"], errors="ignore")
        st.dataframe(rates, hide_index=True, use_container_width=True,
                     column_config={"Adjustment vs League Two":
                                    st.column_config.NumberColumn(format="%.2f")})


if __name__ == "__main__":
    main()
