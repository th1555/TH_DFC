# TH_DFC — Dumbarton FC recruitment engine

A low-cost "Moneyball for Scottish League Two" tool. It scans available players,
puts them on one common **SL2-equivalent** output scale despite playing in
leagues of different strength, and surfaces a ranked shortlist of strikers who
resemble proven SL2 success — displayed in a simple web app.

**It is decision support, not a verdict.** The tool proposes; a human decides.
It cannot see character, attitude, injuries, or fit — the things that actually
decide signings at this level.

---

## Scope & limitations (read this first)

This is a **prototype on free data** — a coverage-and-filtering aid, not a
fine-grained player evaluator. Being explicit about that is the point:

- It ranks on **counting stats** (goal contributions per appearance) in a tier
  where samples are small. Treat the output as directional bands ("these are all
  plausible") — **not** a precise order ("0.91 beats 0.88").
- Counting stats are **style-blind**: a poacher and a link-up forward with the
  same tally look identical. The tool can't tell them apart — a human must.
- The league-equivalency coefficients come from a modest number of movers and
  carry survivorship bias. Trust them more where the mover count is higher.

**What it does well:** systematic coverage of an availability pool nobody at this
level tracks, on a common SL2-equivalent scale — turning "we have no idea who's
out there" into "here are the names worth watching."

**What unlocks the next level: paid event data** (Wyscout / Opta-grade) — xG,
shot quality, involvement, defensive actions, style-of-play similarity. That is
what turns coarse filtering into real player *evaluation*. Free data at SL2 has
no event-data option (StatsBomb/Understat stop at elite leagues; FBref lost Opta
in Jan 2026 and never covered the fourth tier), so this tool is deliberately the
**front-end filter**, and paid event data is the **upgrade lane** it feeds into.

---

## What it does (and doesn't, yet)

- **Does:** learns a league "exchange rate" from players who actually moved
  between leagues, translates everyone's output onto an SL2 scale, and ranks
  strikers by resemblance to proven SL2 output. All on free data.
- **Not yet:** availability and affordability. Those need a Transfermarkt market
  layer (age, value, contract, free-agent status) that isn't wired in. Until it
  is, the shortlist ranks on **fit only** — "who resembles proven SL2 strikers?",
  not "who can we sign?".
- **Honest about data volume:** coefficients and the SL2 reference only become
  trustworthy once you've ingested many squads across several leagues and
  seasons. The scripts say so plainly rather than faking precision.

See `docs/how-the-scores-work.md` for the plain-language scoring explainer.

---

## How it fits together

```
fotmob_squad.py     team id  -> squad of player ids
      |
ingest_fotmob.py    player ids -> per-season output (goals, assists, apps, minutes)
      |
store_pipeline.py   loads the store, then:
      |               - league_equivalency.py / equivalency_real.py  -> coefficients
      |               - fit ranking                                   -> shortlist
      v
dumbarton.db        the SQLite store (players, stats, coefficients, shortlist)
      |
app.py              read-only Streamlit UI over the store
```

The store is the backbone: data **accumulates** by key (new seasons append, they
don't overwrite), every scraped row is stamped with its **source + fetch time**,
and the human **`recruitment_status`** table is walled off so a data refresh can
never wipe a scout's notes (that layer is defined but not yet built).

---

## Files

**Application (run these):**
| File | Role |
|---|---|
| `app.py` | Read-only Streamlit UI — the deploy entry point |
| `store_pipeline.py` | One command: CSV → store → coefficients → shortlist |
| `db.py` | The SQLite store + data-access layer |
| `league_equivalency.py` | Core estimator (+ synthetic self-validation) |
| `equivalency_real.py` | Runs the estimator on real FotMob CSVs |
| `matching_real.py` | Real-data fit ranking (standalone, also folds in a market file) |
| `ingest_fotmob.py` | FotMob player pages → per-season output table |
| `fotmob_squad.py` | FotMob team id → squad of player ids |
| `matching_engine.py` | Synthetic matching demo (reference; not in the live path) |

**Data:**
| File | Role |
|---|---|
| `dumbarton.db` | The store. Commit it **after your first local data run** so the deployed app shows real players. Until then the app shows clearly-labelled demo data. |

**Docs & diagnostics:**
| Path | Role |
|---|---|
| `docs/how-the-scores-work.md` | Plain-language scoring guide |
| `docs/setup-pycharm.md` | Step-by-step local setup |
| `docs/recruitment-spec.md` | The full build spec |
| `probes/` | Diagnostic scripts to re-lock the parsers if FotMob/Transfermarkt change their page structure |

---

## Setup

```
pip install -r requirements.txt
```

(Python 3.10+. `docs/setup-pycharm.md` has a click-by-click version.)

---

## Running it

There are two separate runs, and one of them **must be local**.

### 1. The data run (local only)

FotMob and Transfermarkt block datacenter IPs, so scraping must run from a normal
home connection — **not** in the cloud.

```
python fotmob_squad.py 8409 8235 <more team ids…>     # -> fotmob_squad.csv
python ingest_fotmob.py --from-csv fotmob_squad.csv   # -> fotmob_player_seasons.csv
python store_pipeline.py fotmob_player_seasons.csv     # -> builds/updates dumbarton.db
```

Get team ids from the FotMob URL: `fotmob.com/teams/{ID}/…`. For a list worth
trusting, ingest all ~10 SL2 clubs plus feeder-league clubs (Highland, Lowland)
and some League One clubs — the cross-league moves are what power the exchange
rates. Ingestion is rate-limited (~3s/player), so a few hundred players takes
several minutes. Data accumulates across runs, so each squad you add improves
the next list.

### 2. The app (local, then cloud)

```
streamlit run app.py
```

With no `dumbarton.db` present it shows demo data (banner-flagged) so you can see
the interface immediately. Once you've done a data run, it shows real players.

---

## Deploying to Streamlit Cloud

The app is **read-only** and never scrapes, which is exactly why it can live on
Streamlit Cloud. The catch: the cloud can't scrape, so the **database travels
with the repo**.

1. Do a local data run to build `dumbarton.db`.
2. Commit `app.py`, `requirements.txt` and `dumbarton.db`.
3. Point Streamlit Cloud at the repo (main file: `app.py`).
4. To refresh: re-run the pipeline locally, commit the updated `dumbarton.db`.

Automating that refresh (an always-on local machine pushing a fresh database on a
schedule) is a future step, not required to get started.

---

## Roadmap

- **Transfermarkt market layer** — age, value, contract, free-agent status → turns
  the fit list into a *signable* shortlist (availability × affordability).
- **Human-in-the-loop layer** — write-back status (watch / contact / trial /
  passed) + notes into `recruitment_status`, protected from data refreshes.
- **Automated refresh** — scheduled local scrape → committed database.
- **Beyond strikers** — the V1 scope is attackers, where counting stats mean the
  most; the same pipeline extends per position.

---

## Data & ethics

Uses public data from FotMob (productivity/minutes) and, in future, Transfermarkt
(market data). Respect each site's terms and rate limits, cache aggressively, and
don't redistribute raw data. This is low-impact, public-interest recruitment
research for a small club.
