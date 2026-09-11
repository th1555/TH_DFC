#!/usr/bin/env python3
"""
db.py  —  the persistent store for the Dumbarton recruitment engine
===================================================================
One SQLite file gives every kind of data a home, with three principles baked in:
  * ACCUMULATE, don't overwrite — stats keyed by (player, season, league),
    upserted, so new seasons append and history builds up.
  * PROVENANCE — scraped rows carry source + fetched_at (how stale is this?).
  * WALL OFF THE HUMAN LAYER — `recruitment_status` is a separate table the
    scrapers NEVER touch. Defined now, filled later: a data refresh can never
    wipe a scout's work.
Canonical league mapping lives in a REFERENCE table, not hard-coded.
"""
from __future__ import annotations
import sqlite3
from datetime import datetime, timezone
import pandas as pd

DB_PATH = "dumbarton.db"


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


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
  player_id INTEGER PRIMARY KEY, name TEXT, position TEXT,
  current_team_id INTEGER, source TEXT, fetched_at TEXT
);
CREATE TABLE IF NOT EXISTS player_season_stats (
  player_id INTEGER, season TEXT, league_id INTEGER, tournament_id INTEGER,
  league_name TEXT, appearances INTEGER, goals INTEGER, assists INTEGER,
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
CREATE TABLE IF NOT EXISTS shortlist (
  player_id INTEGER PRIMARY KEY, name TEXT, league TEXT, season TEXT,
  adj_per_app REAL, appearances INTEGER, fit REAL, score REAL,
  flags TEXT, computed_at TEXT
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


def init_db(conn):
    conn.executescript(SCHEMA)
    conn.executemany(
        "INSERT OR IGNORE INTO ref_leagues "
        "(league_id,fotmob_name,canonical,tier,is_cup,is_peer) VALUES (?,?,?,?,?,?)",
        SEED_LEAGUES)
    conn.commit()


def upsert_players(conn, df):
    rows = [(int(r.player_id), r.get("player_name"), r.get("position"),
             None, "fotmob", now()) for _, r in df.iterrows()]
    conn.executemany(
        "INSERT INTO players (player_id,name,position,current_team_id,source,fetched_at) "
        "VALUES (?,?,?,?,?,?) ON CONFLICT(player_id) DO UPDATE SET "
        "name=excluded.name, position=excluded.position, fetched_at=excluded.fetched_at",
        rows)
    conn.commit()


def upsert_stats(conn, df):
    rows = []
    for _, r in df.iterrows():
        mins = r.get("minutes")
        rows.append((int(r.player_id), str(r.season), int(r.get("league_id", 0) or 0),
                     int(r.get("tournament_id", 0) or 0), r.get("league"),
                     int(r.appearances), int(r.goals), int(r.assists),
                     int(r.goal_contribs),
                     None if pd.isna(mins) else int(mins),
                     float(r.per_app), int(bool(r.get("is_cup"))),
                     r.get("transfer_type"), "fotmob", now()))
    conn.executemany(
        "INSERT INTO player_season_stats VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
        "ON CONFLICT(player_id,season,league_id) DO UPDATE SET "
        "appearances=excluded.appearances, goals=excluded.goals, "
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
    conn.execute("DELETE FROM shortlist")
    df = df.copy(); df["computed_at"] = now()
    df.to_sql("shortlist", conn, if_exists="append", index=False)
    conn.commit()


def league_maps(conn):
    ref = pd.read_sql("SELECT * FROM ref_leagues", conn)
    return (dict(zip(ref.league_id, ref.canonical)),
            dict(zip(ref.fotmob_name, ref.canonical)),
            dict(zip(ref.league_id, ref.is_cup.astype(bool))))


def get_stats_df(conn):
    return pd.read_sql(
        "SELECT s.*, p.name AS player_name, p.position AS position "
        "FROM player_season_stats s LEFT JOIN players p USING(player_id)", conn)


def get_coefficients(conn):
    return pd.read_sql("SELECT * FROM league_coefficients ORDER BY coeff_to_sl2", conn)


def get_shortlist(conn):
    return pd.read_sql("SELECT * FROM shortlist ORDER BY score DESC", conn)


if __name__ == "__main__":
    c = connect(); init_db(c)
    print("initialised store at", DB_PATH)
    print("tables:", [r[0] for r in c.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")])
    print("seeded leagues:", len(pd.read_sql('SELECT * FROM ref_leagues', c)))
