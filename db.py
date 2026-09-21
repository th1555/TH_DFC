#!/usr/bin/env python3
"""
db.py  —  persistent store for the Dumbarton recruitment engine
===============================================================
Accumulates by key; stamps provenance; walls off the human layer
(recruitment_status). Canonical league mapping lives in ref_leagues.
Stores club (team) per season and age per player; shortlist is a computed
table replaced wholesale each run.
"""
from __future__ import annotations
import sqlite3
from datetime import datetime, timezone
import pandas as pd

DB_PATH = "dumbarton.db"


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _int_safe(v, default=0):
    """int() that survives NaN / None / blanks from CSVs."""
    try:
        if pd.isna(v):
            return default
    except (TypeError, ValueError):
        pass
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def connect(path=DB_PATH):
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


SCHEMA = """
CREATE TABLE IF NOT EXISTS ref_leagues (
  league_id INTEGER PRIMARY KEY, fotmob_name TEXT, canonical TEXT,
  tier INTEGER, is_cup INTEGER DEFAULT 0, is_peer INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS teams (
  team_id INTEGER PRIMARY KEY, name TEXT, league_id INTEGER,
  source TEXT, fetched_at TEXT
);
CREATE TABLE IF NOT EXISTS players (
  player_id INTEGER PRIMARY KEY, name TEXT, position TEXT, age INTEGER,
  current_team_id INTEGER, source TEXT, fetched_at TEXT
);
CREATE TABLE IF NOT EXISTS player_season_stats (
  player_id INTEGER, season TEXT, league_id INTEGER, tournament_id INTEGER,
  league_name TEXT, team TEXT, appearances INTEGER, goals INTEGER, assists INTEGER,
  goal_contribs INTEGER, minutes INTEGER, per_app REAL, is_cup INTEGER,
  transfer_type TEXT, source TEXT, fetched_at TEXT,
  PRIMARY KEY (player_id, season, league_id)
);
CREATE TABLE IF NOT EXISTS market_data (
  player_id INTEGER PRIMARY KEY, age INTEGER, market_value INTEGER,
  contract_expiry TEXT, availability TEXT, source TEXT, fetched_at TEXT
);
CREATE TABLE IF NOT EXISTS league_coefficients (
  canonical TEXT PRIMARY KEY, coeff_to_sl2 REAL, n_movers INTEGER,
  linked INTEGER, computed_at TEXT
);
CREATE TABLE IF NOT EXISTS recruitment_status (
  player_id INTEGER PRIMARY KEY, status TEXT, notes TEXT, updated_at TEXT
);
"""

SEED_LEAGUES = [
    (125, "League Two",    "SL2",           2, 0, 1),
    (124, "League One",    "League One",    3, 0, 1),
    (123, "Championship",  "Championship",  4, 0, 0),
    (66,  "Premiership",   "Premiership",   5, 0, 0),
    (179, "Challenge Cup", "Challenge Cup", 0, 1, 0),
]

# columns added after the original schema shipped — applied to existing DBs too
MIGRATIONS = [
    ("player_season_stats", "team", "TEXT"),
    ("players", "age", "INTEGER"),
]


def init_db(conn):
    conn.executescript(SCHEMA)
    for table, col, typ in MIGRATIONS:
        try:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {typ}")
        except sqlite3.OperationalError:
            pass  # already exists
    conn.executemany(
        "INSERT OR IGNORE INTO ref_leagues "
        "(league_id,fotmob_name,canonical,tier,is_cup,is_peer) VALUES (?,?,?,?,?,?)",
        SEED_LEAGUES)
    conn.commit()


def upsert_players(conn, df):
    seen = {}
    for _, r in df.iterrows():
        pid = _int_safe(r.player_id, None)
        if pid is None or pid in seen:
            continue
        seen[pid] = (pid, r.get("player_name"), r.get("position"),
                     _int_safe(r.get("age"), None), None, "fotmob", now())
    conn.executemany(
        "INSERT INTO players (player_id,name,position,age,current_team_id,source,fetched_at) "
        "VALUES (?,?,?,?,?,?,?) ON CONFLICT(player_id) DO UPDATE SET "
        "name=excluded.name, position=excluded.position, "
        "age=COALESCE(excluded.age, players.age), fetched_at=excluded.fetched_at",
        list(seen.values()))
    conn.commit()


def upsert_stats(conn, df):
    rows = []
    for _, r in df.iterrows():
        mins = r.get("minutes")
        per_app = 0.0 if pd.isna(r.get("per_app")) else float(r.per_app)
        rows.append((_int_safe(r.player_id), str(r.season), _int_safe(r.get("league_id")),
                     _int_safe(r.get("tournament_id")), r.get("league"), r.get("team"),
                     _int_safe(r.appearances), _int_safe(r.goals), _int_safe(r.assists),
                     _int_safe(r.goal_contribs),
                     None if pd.isna(mins) else _int_safe(mins),
                     per_app, _int_safe(bool(r.get("is_cup"))),
                     r.get("transfer_type"), "fotmob", now()))
    conn.executemany(
        "INSERT INTO player_season_stats VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
        "ON CONFLICT(player_id,season,league_id) DO UPDATE SET "
        "team=excluded.team, appearances=excluded.appearances, goals=excluded.goals, "
        "assists=excluded.assists, goal_contribs=excluded.goal_contribs, "
        "minutes=excluded.minutes, per_app=excluded.per_app, "
        "fetched_at=excluded.fetched_at", rows)
    conn.commit()


def save_coefficients(conn, coeff, counts, linked):
    conn.execute("DELETE FROM league_coefficients")
    conn.executemany(
        "INSERT INTO league_coefficients VALUES (?,?,?,?,?)",
        [(l, float(c), int(counts.get(l, 0)), int(l in linked), now())
         for l, c in coeff.items()])
    conn.commit()


def save_shortlist(conn, df):
    # computed table — replace wholesale, take whatever columns surface() emits
    df = df.copy(); df["computed_at"] = now()
    df.to_sql("shortlist", conn, if_exists="replace", index=False)
    conn.commit()


def league_maps(conn):
    ref = pd.read_sql("SELECT * FROM ref_leagues", conn)
    return (dict(zip(ref.league_id, ref.canonical)),
            dict(zip(ref.fotmob_name, ref.canonical)),
            dict(zip(ref.league_id, ref.is_cup.astype(bool))))


def get_stats_df(conn):
    return pd.read_sql(
        "SELECT s.*, p.name AS player_name, p.position AS position, p.age AS age "
        "FROM player_season_stats s LEFT JOIN players p USING(player_id)", conn)


def get_coefficients(conn):
    return pd.read_sql("SELECT * FROM league_coefficients ORDER BY coeff_to_sl2", conn)


def get_history(conn, pid):
    return pd.read_sql(
        "SELECT season, team, league_name AS league, appearances, goals, assists, "
        "minutes, per_app, is_cup, transfer_type FROM player_season_stats "
        "WHERE player_id=? ORDER BY season DESC", conn, params=(int(pid),))


if __name__ == "__main__":
    c = connect(); init_db(c)
    print("initialised", DB_PATH, "|", [r[0] for r in c.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")])
