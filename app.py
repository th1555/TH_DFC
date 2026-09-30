#!/usr/bin/env python3
"""
app.py — Dumbarton FC recruitment dashboard (career model + now/forward toggle)
==============================================================================
Plain-language, read-only. Rates forwards on a recency-weighted SL2-equivalent
career level, keeps club/league/age CURRENT, shows peak season + trajectory, and
lets the user flip the ranking between "best right now" and "best going forward"
(age curve + momentum). Joins Transfermarkt contract/availability where matched.
Demo-data fallback if no real store is present.  Run:  streamlit run app.py
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
DEFAULTS = dict(w_out=70, w_dur=30, penalise=False, mode="Best right now")


# ---------------------------------------------------------------------------
# data access
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
    try:
        mk = pd.read_sql("SELECT player_id, contract_expiry, availability "
                         "FROM market_data", conn)
        if len(mk) and "player_id" in sl.columns:
            sl = sl.merge(mk, on="player_id", how="left")
    except Exception:
        pass
    conn.close()
    return sl, co


AVAIL_LABEL = {"expiring": "Contract expiring", "lapsed": "Out of contract?",
               "contracted": "Under contract", "unknown": "Unknown"}


def avail_label(v):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return "Not checked"
    return AVAIL_LABEL.get(str(v), "Not checked")


TREND_LABEL = {"rising": "↑ Rising", "steady": "→ Steady", "declining": "↓ Declining"}


def trend_label(trend, stepped):
    base = TREND_LABEL.get(str(trend), "→ Steady")
    return "⤴ Stepped up" if stepped else base


def history(path, _mtime, pid):
    conn = sqlite3.connect(path)
    cols = [c[1] for c in conn.execute("PRAGMA table_info(player_season_stats)")]
    club_sel = "team AS club" if "team" in cols else "'' AS club"
    cup = "AND (is_cup IS NULL OR is_cup=0)" if "is_cup" in cols else ""
    df = pd.read_sql(
        f"SELECT season, {club_sel}, league_name AS league, appearances, goals, "
        f"assists, minutes, per_app, transfer_type FROM player_season_stats "
        f"WHERE player_id=? {cup} ORDER BY season DESC", conn, params=(int(pid),))
    conn.close()
    return df


# ---------------------------------------------------------------------------
# scoring: career level -> now / forward ratings
# ---------------------------------------------------------------------------
def age_factor(a):
    """'Years of peak value remaining' proxy for forwards."""
    if a is None or (isinstance(a, float) and pd.isna(a)):
        return 0.90
    a = int(a)
    if a <= 19:
        return 0.90
    if a <= 26:
        return 1.00
    if a <= 28:
        return 0.92
    if a <= 30:
        return 0.82
    if a <= 32:
        return 0.70
    if a <= 34:
        return 0.58
    return 0.48


def traj_factor(trend, stepped):
    f = {"rising": 1.08, "steady": 1.0, "declining": 0.90}.get(str(trend), 1.0)
    return max(f, 1.15) if stepped else f


def score(df, ref, target_apps, w_out, w_dur, mode, penalise):
    ref = np.sort(ref) if len(ref) else np.array([0.0])
    out = np.searchsorted(ref, df.level.values, "right") / max(1, len(ref))
    dur = np.minimum(1.0, df.career_apps.values / max(1, target_apps))
    base = (w_out * out + w_dur * dur) / max(1, (w_out + w_dur))
    if mode == "forward":
        af = np.array([age_factor(a) for a in df.age])
        tf = np.array([traj_factor(t, s) for t, s in zip(df.trend, df.stepped_up)])
        base = base * af * tf
    if penalise and "flags" in df:
        weak = df.flags.fillna("").str.contains("weaker league").values
        base = base * np.where(weak, 0.9, 1.0)
    return np.clip(np.round(base, 3), 0, 1)


# ---------------------------------------------------------------------------
# demo store (new schema)
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
    conn.executemany("INSERT INTO league_coefficients VALUES (?,?,?,?)",
                     [("Highland / Lowland", 0.67, 13, 1), ("SL2", 1.00, 99, 1),
                      ("League One", 1.32, 92, 1), ("Championship", 1.41, 32, 1),
                      ("Premiership", 2.54, 7, 1)])
    # player_id,name,club,league,pos,age,level,peak,peak_season,peak_league,trend,
    # stepped,cap,cg,ca,avail,contract
    demo = [
        (1, "DEMO — Young Riser",   "Demo City",     "SL2",  "Striker",       22, 0.62, 0.66, "2025", "Highland / Lowland", "steady",   1, 40, 30, 8, "expiring",   "2026-06-30"),
        (2, "DEMO — Peak Poacher",  "Demo Rovers",   "SL2",  "Striker",       26, 0.66, 0.70, "2026", "SL2",                "rising",   0, 62, 28, 6, "expiring",   "2026-06-30"),
        (3, "DEMO — Veteran Ace",   "Demo Athletic", "SL2",  "Striker",       34, 0.71, 0.75, "2026", "SL2",                "steady",   0, 90, 40, 9, "contracted", "2027-05-31"),
        (4, "DEMO — Fading Winger", "Demo United",   "SL2",  "Right Winger",  30, 0.44, 0.68, "2023", "SL2",                "declining",0, 88, 12, 10,"lapsed",     "2025-05-31"),
        (5, "DEMO — Steady Wide",   "Demo Thistle",  "SL2",  "Left Winger",   24, 0.48, 0.51, "2025", "SL2",                "steady",   0, 66, 14, 7, "expiring",   "2026-06-30"),
    ]
    cols = ["player_id","name","club","league","position","age","level","peak",
            "peak_season","peak_league","trend","stepped_up","career_apps",
            "career_goals","career_assists","availability","contract_expiry"]
    df = pd.DataFrame([d[:len(cols)] for d in demo], columns=cols)
    df["raw_level"] = (df.level / df.league.map({"SL2": 1.0})).round(3)
    df["last_league"] = df.league; df["last_apps"] = 30
    df["flags"] = ["", "", "", "", ""]
    df["computed_at"] = "2026-01-01T00:00:00+00:00"
    df.to_sql("shortlist", conn, if_exists="replace", index=False)
    hist = []
    for pid, name, club, lg, *_ in demo:
        hist.append((pid, "2026", club, "League Two", 12, 5, 2, 960, 0.58, 0, "free transfer"))
        hist.append((pid, "2025", club, "League Two", 30, 12, 5, 2400, 0.57, 0, None))
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
    holder = st
    if os.path.exists("crest.png"):
        c1, c2 = st.columns([1, 13]); c1.image("crest.png", width=56); holder = c2
    holder.markdown(
        '<div class="dfc-header"><h1>DUMBARTON FC · RECRUITMENT</h1>'
        '<p>Sons of the Rock — a tool to help find forward players</p></div>',
        unsafe_allow_html=True)


def main():
    st.set_page_config(page_title="Dumbarton FC — Recruitment", page_icon="⚽", layout="wide")
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
    updated = str(sl.computed_at.max())[:10] if "computed_at" in sl.columns and len(sl) else "—"

    st.markdown(
        "#### What this is\n"
        "A tool that suggests **forward players who might suit Dumbarton**. It sums up "
        "each player's goals and assists across recent seasons, **adjusts for how strong "
        "their league is**, and keeps their **current club and age** front and centre. "
        "The players near the top are **most worth watching** — a shortlist to guide you, "
        "**not a final decision**.")
    src = st.columns([3, 1])
    src[0].markdown("📊 **Where the numbers come from:** FotMob (public football stats) "
                    "and Transfermarkt (contract dates). Rankings are worked out "
                    "automatically — not anyone's opinion.")
    src[1].markdown(f"🕓 **Data last updated:**\n\n{updated}")
    with st.expander("What this tool can and cannot do — please read"):
        st.markdown(
            "**It can:** scan players you'd never have time to watch, compare them fairly "
            "across leagues, weigh recent form and career record, and flag who's on the up.\n\n"
            "**A person still decides everything.** It's a guide, not a verdict.\n\n"
            "**It cannot** judge playing style, attitude or fitness — that needs your eyes "
            "(or paid video/data).\n\n"
            "**Ratings are directional** — read a 90 vs 88 as 'both strong', not a ranking.")
    if demo:
        st.warning("This is **example data**, not real players — it shows how the tool "
                   "looks.", icon="⚠️")

    with st.sidebar:
        st.header("Rank players by")
        mode_label = st.radio(
            "", ["Best right now", "Best going forward"], key="mode",
            help="'Best right now' rates pure output. 'Best going forward' also rewards "
                 "younger players and those on the up, and eases off older players "
                 "(who won't improve) — better for a signing you'll keep a few years.")
        mode = "forward" if mode_label == "Best going forward" else "now"

        st.divider(); st.header("Narrow the list")
        positions = sorted(sl.position.dropna().unique()) if "position" in sl else []
        pick_pos = st.multiselect("Position", positions, default=positions)
        leagues = sorted(sl.league.dropna().unique())
        pick_lg = st.multiselect("Current league", leagues, default=leagues,
                                 help="Where the player is NOW.")
        min_apps = st.slider("Minimum games (recent seasons)", 0,
                             int(sl.career_apps.max()) if len(sl) else 100, 0)
        exclude = st.text_input("Hide a club (e.g. Dumbarton)").strip().lower()
        q = st.text_input("Search by name").strip().lower()
        avail_opts = sorted(sl.availability.dropna().unique()) if "availability" in sl else []
        pick_avail = st.multiselect(
            "Availability", avail_opts, default=avail_opts,
            help="From Transfermarkt contract dates.") if avail_opts else []

        with st.expander("⚙️ Advanced (optional)"):
            st.button("Reset", on_click=lambda: st.session_state.update(DEFAULTS))
            w_out = st.slider("Value output", 0, 100, key="w_out")
            w_dur = st.slider("Value games played", 0, 100, key="w_dur")
            penalise = st.checkbox("Be stricter on weak-league peaks", key="penalise")

    view = sl.copy()
    if pick_pos:
        view = view[view.position.isin(pick_pos)]
    view = view[view.league.isin(pick_lg) & (view.career_apps >= min_apps)]
    if exclude:
        view = view[~view.club.fillna("").str.lower().str.contains(exclude)]
    if q:
        view = view[view.name.str.lower().str.contains(q)]
    if "availability" in view.columns and pick_avail:
        view = view[view.availability.isin(pick_avail) | view.availability.isna()]

    ref = sl[sl.league == "SL2"].level.values
    target = int(sl[sl.league == "SL2"].career_apps.median()) if (sl.league == "SL2").any() else 60
    if len(view):
        view["rn"] = (score(view, ref, target, w_out, w_dur, "now", penalise) * 100).round().astype(int)
        view["rf"] = (score(view, ref, target, w_out, w_dur, "forward", penalise) * 100).round().astype(int)
        view["rating"] = view.rf if mode == "forward" else view.rn
        view["trend_plain"] = [trend_label(t, s) for t, s in zip(view.trend, view.stepped_up)]
        if "availability" in view.columns:
            view["availability_plain"] = view.availability.apply(avail_label)
        view = view.sort_values("rating", ascending=False).reset_index(drop=True)

    tab_list, tab_rates = st.tabs(["⭐ Recommended players", "📈 How leagues compare"])

    with tab_list:
        st.subheader(f"{len(view)} players — ranked by "
                     f"'{'Best going forward' if mode=='forward' else 'Best right now'}'")
        if len(view):
            st.caption("Current league:  " + "   ".join(
                f"**{k}** {v}" for k, v in view.league.value_counts().items()))
        with st.expander("How to read this"):
            st.markdown(
                "- **Fit rating** — 0–100, from the mode picked on the left. 'Right now' = "
                "pure adjusted output; 'Going forward' also rewards youth and momentum.\n"
                "- **Output level** — goals + assists per game across recent seasons, adjusted "
                "to a League Two scale, weighted toward recent form.\n"
                "- **Best season** — their peak adjusted output, and where it came from.\n"
                "- **Trajectory** — rising / steady / declining, and ⤴ if they recently stepped "
                "up a level and held their own.\n"
                "- **Availability** — from Transfermarkt contract dates where matched.")
        cc = {
            "name": st.column_config.TextColumn("Player"),
            "club": st.column_config.TextColumn("Current club"),
            "league": st.column_config.TextColumn("League"),
            "position": st.column_config.TextColumn("Position"),
            "age": st.column_config.NumberColumn("Age"),
            "rating": st.column_config.ProgressColumn("Fit rating", min_value=0, max_value=100, format="%d"),
            "level": st.column_config.NumberColumn("Output level (adj)", format="%.2f",
                     help="Recent-seasons G+A per game, adjusted to a League Two scale."),
            "peak": st.column_config.NumberColumn("Best season", format="%.2f"),
            "trend_plain": st.column_config.TextColumn("Trajectory"),
            "career_apps": st.column_config.NumberColumn("Games"),
            "career_goals": st.column_config.NumberColumn("Goals"),
            "career_assists": st.column_config.NumberColumn("Assists"),
            "availability_plain": st.column_config.TextColumn("Availability"),
        }
        order = ["name", "club", "league", "position", "age", "rating", "level",
                 "peak", "trend_plain", "career_apps", "career_goals",
                 "career_assists", "availability_plain"]
        order = [c for c in order if c in view.columns]
        st.dataframe(view[order], hide_index=True, use_container_width=True, column_config=cc)
        if len(view):
            st.download_button("⬇️ Download this list (opens in Excel)",
                               view[order].to_csv(index=False), "shortlist.csv", "text/csv")

        st.divider(); st.subheader("See one player in detail")
        if len(view):
            who = st.selectbox("Player", view.name.tolist(), label_visibility="collapsed")
            r = view[view.name == who].iloc[0]
            t = st.columns(5)
            t[0].metric("Current club", r.get("club") or "—")
            t[1].metric("Position", r.get("position") or "—")
            t[2].metric("Age", int(r.age) if has_age and pd.notna(r.get("age")) else "—")
            t[3].metric("Current league", r.get("league") or "—")
            t[4].metric("Trajectory", trend_label(r.get("trend"), r.get("stepped_up")))
            # both ratings, always visible
            rr = st.columns(4)
            rr[0].metric("Rating — right now", f"{int(r.get('rn', 0))} / 100")
            rr[1].metric("Rating — going forward", f"{int(r.get('rf', 0))} / 100",
                         help="Adjusted for age and momentum.")
            rr[2].metric("Output level (adj)", f"{r.get('level', float('nan')):.2f}")
            rr[3].metric("Best season", f"{r.get('peak', float('nan')):.2f}",
                         help=f"Peak in {r.get('peak_season','?')} "
                              f"({r.get('peak_league','?')})")
            av, cu = r.get("availability"), r.get("contract_expiry")
            if av is not None and not pd.isna(av):
                st.success(f"**Availability:** {avail_label(av)}" +
                           (f"  ·  contract until {str(cu)[:10]}"
                            if cu is not None and not pd.isna(cu) else ""))
            else:
                st.caption("No Transfermarkt contract/availability matched for this player yet.")
            if r.get("flags"):
                st.info(f"Note: {r.flags}")
            st.markdown("**Season-by-season record** (their real numbers, not adjusted)")
            st.dataframe(history(path, mtime, int(r.player_id)), hide_index=True,
                         use_container_width=True, column_config={
                             "season": "Season", "club": "Club", "league": "League",
                             "appearances": "Games", "goals": "Goals", "assists": "Assists",
                             "minutes": "Minutes",
                             "per_app": st.column_config.NumberColumn("G+A/game", format="%.2f"),
                             "transfer_type": "Move that summer"})

    with tab_rates:
        st.subheader("How we compare different leagues")
        st.markdown(
            "Leagues aren't equal — it's harder to score in the Championship than the "
            "Highland League. So we translate everyone's output onto a **League Two scale**. "
            "Below 1.0 = weaker league (output reduced); above 1.0 = stronger (boosted). "
            "These are learned from players who **actually moved** between leagues.")
        st.bar_chart(co.set_index("canonical")["coeff_to_sl2"])
        st.dataframe(co.rename(columns={"canonical": "League",
                     "coeff_to_sl2": "Adjustment vs League Two",
                     "n_movers": "Players moved (evidence)"}).drop(columns=["linked"], errors="ignore"),
                     hide_index=True, use_container_width=True)


if __name__ == "__main__":
    main()
