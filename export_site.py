#!/usr/bin/env python3
"""
export_site.py  —  build the shareable website from dumbarton.db
================================================================
Reads the finished store (shortlist, season histories, league exchange rates,
Transfermarkt contract data) and writes ONE self-contained page:

    site/index.html      <- this is what Cloudflare Pages serves

The page design lives in site_template.html; this script injects the data into
it. Run it after store_pipeline.py and match_market.py:

    python export_site.py

Then commit and push; Cloudflare Pages redeploys automatically.
Deps: pandas (+ db.py and a built dumbarton.db)
"""
import json
import os
import re
import shutil
import sqlite3
import pandas as pd
import db

TEMPLATE = "site_template.html"
OUT_DIR = "site"
MARK = "/*__DATA__*/null"


def pos_group(p):
    p = str(p or "").lower()
    if "wing" in p:
        return "Winger"
    if "attack" in p and "mid" in p:
        return "Attacking midfielder"
    return "Striker"


def clean(v):
    """JSON-safe scalar (NaN/None -> None, numpy -> python)."""
    if v is None:
        return None
    try:
        if pd.isna(v):
            return None
    except (TypeError, ValueError):
        pass
    if hasattr(v, "item"):
        return v.item()
    return v


def main():
    if not os.path.exists(db.DB_PATH):
        raise SystemExit("No dumbarton.db here. Run store_pipeline.py first.")
    conn = sqlite3.connect(db.DB_PATH)
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}

    sl = pd.read_sql("SELECT * FROM shortlist", conn)
    if "level" not in sl.columns:
        raise SystemExit("This dumbarton.db was built by an older pipeline. "
                         "Delete it and re-run store_pipeline.py first.")
    if "market_data" in tables:
        mk = pd.read_sql("SELECT player_id, contract_expiry, availability FROM market_data", conn)
        sl = sl.merge(mk, on="player_id", how="left")

    co = pd.read_sql("SELECT canonical, coeff_to_sl2, n_movers FROM league_coefficients", conn)
    rate = dict(zip(co.canonical, co.coeff_to_sl2))

    # FotMob league names -> canonical names, so history rows can be adjusted too
    idmap, namemap, cupmap = db.league_maps(conn)
    hist = pd.read_sql(
        "SELECT player_id, season, team, league_id, league_name, appearances, goals, "
        "assists, per_app, is_cup, transfer_type FROM player_season_stats", conn)
    hist = hist[hist.player_id.isin(sl.player_id)]
    hist["canonical"] = [idmap.get(i) or namemap.get(n, n)
                         for i, n in zip(hist.league_id, hist.league_name)]
    hist["cup"] = [bool(cupmap.get(i, bool(c))) or ("cup" in str(n).lower())
                   for i, c, n in zip(hist.league_id, hist.is_cup, hist.league_name)]
    hist = hist[~hist.cup & (hist.appearances > 0)]
    hist["rate"] = hist.canonical.map(rate)
    hist["adj"] = hist.per_app * hist.rate

    histories = {}
    for pid, g in hist.sort_values("season", ascending=False).groupby("player_id"):
        histories[str(int(pid))] = [
            dict(season=clean(r.season), club=clean(r.team), league=clean(r.canonical),
                 apps=clean(r.appearances), goals=clean(r.goals), assists=clean(r.assists),
                 raw=round(float(r.per_app), 3) if pd.notna(r.per_app) else None,
                 adj=round(float(r.adj), 3) if pd.notna(r.adj) else None,
                 move=clean(r.transfer_type))
            for r in g.itertuples()]

    players = []
    for r in sl.to_dict("records"):
        rec = {k: clean(v) for k, v in r.items() if k != "computed_at"}
        rec["group"] = pos_group(rec.get("position"))
        players.append(rec)

    updated = str(sl.computed_at.max())[:10] if "computed_at" in sl.columns and len(sl) else None
    data = dict(
        updated=updated,
        players=players,
        histories=histories,
        leagues=[dict(name=r.canonical, rate=round(float(r.coeff_to_sl2), 3),
                      movers=int(r.n_movers)) for r in co.itertuples()],
    )
    conn.close()

    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    payload = payload.replace("</", "<\\/")            # safe inside <script>
    html = open(TEMPLATE, encoding="utf-8").read()
    if MARK not in html:
        raise SystemExit(f"{TEMPLATE} is missing the data marker {MARK}")
    html = html.replace(MARK, payload, 1)

    os.makedirs(OUT_DIR, exist_ok=True)
    with open(os.path.join(OUT_DIR, "index.html"), "w", encoding="utf-8") as f:
        f.write(html)
    if os.path.exists("crest.png"):
        shutil.copy("crest.png", os.path.join(OUT_DIR, "crest.png"))
    kb = os.path.getsize(os.path.join(OUT_DIR, "index.html")) // 1024
    print(f"wrote {OUT_DIR}/index.html ({kb} KB): {len(players)} players, "
          f"{sum(len(v) for v in histories.values())} history rows, "
          f"{len(data['leagues'])} leagues, data as of {updated}")


if __name__ == "__main__":
    main()
