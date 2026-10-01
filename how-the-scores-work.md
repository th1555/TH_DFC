# How the scores work

Every forward gets two ratings out of 100: **Right now** (how productive he has
been, adjusted for league strength) and **Going forward** (the same, adjusted for
age and form). Both come from fixed rules applied to FotMob statistics. Contract
status from Transfermarkt is shown alongside but never changes a rating.

This repo is private and the code holds every setting, so this page explains the
method for maintainers. Share the infographic, not this page, outside the project.

---

## 1. What counts

- **Output** = (goals + assists) ÷ games, per league season. Minutes aren't
  reliable at this level, so everything is per game.
- **League games only.** Cups are excluded. If a player appears in two leagues in
  one season, the one with more games is used.
- **A season counts once it has 10 or more games.** Shorter seasons stay on his
  record and show as "this season so far", but don't move his rating.
- **Identity is always current.** Club, league and age come from his latest season.

## 2. Comparing leagues

Each league has an exchange rate against Scottish League Two (fixed at 1.00):

    adjusted output = actual output × league rate

- **Rates are learned from moves.** Every player who changed league between
  consecutive seasons, with at least 5 games and some output on both sides, in
  the last 6 seasons, is evidence. All moves are fitted together; moves with more
  games carry more weight.
- **Leagues are identified by FotMob league ID, never by name.** English League
  Two and Scottish League Two are always separate. `league_info.py` adds each
  league's country so labels read "Championship (England)".
- **Thin leagues are rated cautiously.** A league needs 5 moves for full weight.
  Below that it still gets a rate, pulled towards League Two as if 3 extra moves
  said the leagues were equal, and its seasons count at 20% per move on record.
- **Unlinked leagues get no rate.** A league with no chain of moves to League Two
  shows on a player's record but doesn't count.

## 3. Summarising a career

- **Output level**: a weighted average of adjusted output over his last 4 counted
  seasons. Each season's weight = games × 0.55 per year back × league evidence
  weight. Last season counts about twice the one before.
- **Best season**: his highest adjusted output in a counted season, preferring
  well-evidenced leagues. It can never sit below his output level.
- **Form**: his latest season of 12+ games against his earlier 12+ game seasons.
  15% higher is *Improving*, 15% lower is *Dropping off*, otherwise *Steady*.
  Fewer than two such seasons is *Too early to tell*.
- **Stepped up**: his current league's rate is at least 5% above that of his last
  counted league elsewhere (8+ games there), both well evidenced.
- **Cautions** on his profile: under 20 counted games; best season in a league
  rated 0.70 or below; seasons in thin-evidence leagues.

## 4. The ratings

- **Output score**: the share of current League Two forwards whose output level
  is at or below his (0 to 1).
- **Games score**: his counted games ÷ the typical League Two forward's, capped at 1.

```
Right now      = 100 × min(1, 0.7 × output score + 0.3 × games score)
Going forward  = 100 × min(1, Right now base × age factor × form factor)
```

| Age | Factor |
| --- | --- |
| 19 or under | 0.90 |
| 20–26 | 1.00 |
| 27–28 | 0.92 |
| 29–30 | 0.82 |
| 31–32 | 0.70 |
| 33–34 | 0.58 |
| 35+ | 0.48 |
| Unknown | 0.90 |

| Form | Factor |
| --- | --- |
| Improving | 1.08 |
| Steady / too early to tell | 1.00 |
| Dropping off | 0.90 |
| Stepped up | at least 1.15 |

Several players can score 100 if they out-produce every League Two forward.
Treat those as one top tier, not a strict order.

## 5. Contract status

Transfermarkt players are matched to FotMob players by name and exact date of
birth (name plus birth year if FotMob has no date; name alone only when one
player fits; anything ambiguous is left unmatched). From the contract end date:
*Contract ended*, *Ending soon* (within 8 months), *Under contract*, or *Date
unclear*. Status is calculated when `match_market.py` runs, so rerun it with
every refresh.

## Where the settings live

| Setting | File |
| --- | --- |
| Season minimums, recency, form and step-up rules, thin-league caution | `store_pipeline.py` |
| Rules for which moves count | `equivalency_real.py` |
| League identity and naming | `db.py`, `league_info.py` |
| 70/30 weighting, age and form factors | `site_template.html` |
| Contract window and matching | `match_market.py` |

## Limits

Goals and assists can't separate two strikers with different styles; a 36-game
season is a small sample; league rates are averages and flatter weaker leagues
slightly; team strength is invisible; the age and form factors are judgement
calls, not learned. The tool narrows the field. People make the decision.
