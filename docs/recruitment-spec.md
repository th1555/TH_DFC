# Dumbarton FC — SL2 "Moneyball" Recruitment Engine

**Build-ready specification (V1 — no Wyscout)**
Systematically scan every pool of available players (free agents, out-of-contract, inferred loan candidates, feeder leagues), put them on a common quality scale despite playing in leagues of different strength, and rank those who resemble proven Scottish League Two success — as a human-in-the-loop shortlist.

---

## 1. Purpose & framing

This is **not** an advanced-analytics play — the data floor forbids it (see §2). It's a **market-inefficiency-plus-coverage** play, which is truer to the original Moneyball idea anyway. The edge isn't a fancier metric than everyone else; it's that **no one at SL2 level has the time or tools to systematically monitor the entire availability pool and match it against what actually works.** A part-time recruitment setup runs on contacts and word of mouth. This tool runs on free data and never sleeps.

**Posture:** the tool proposes a ranked shortlist with reasons; the manager/scout disposes. It never signs anyone. Character, attitude, physicality, and fit are exactly the things the free data *can't* see — so a human in the loop isn't a safety nicety here, it's structurally required.

**Output:** a ranked candidate shortlist into a HITL queue (same pattern as the sponsor tool), each row carrying league-adjusted stats, resemblance to named SL2 successes, availability status, an affordability estimate, and honest caveat flags.

---

## 2. The honest data floor (V1 constraints)

- **No cheap advanced data exists for SL2.** FBref lost its Opta licence in Jan 2026 (advanced stats no longer update) and never covered the fourth tier anyway. xG, passing, defensive actions, tracking — off the table for V1.
- **Wyscout is the industry tool** but is club/membership access, not a personal subscription. Treated here as a **future upgrade path**, not a V1 dependency.
- **What V1 runs on:** basic counting stats (goals, assists, appearances, **minutes** — sourced from **FotMob**, confirmed available down to SL2) + **market data** (free-agent flags, contract-expiry dates, market values, squad lists — from **Transfermarkt**). Two free sources, joined on player identity. (Note: TM's per-player performance page moved off table markup, so minutes come from FotMob, not TM — a resolved data-plumbing detail, not a data gap.)

Say this plainly in any pitch. Claiming more than counting-plus-market data at this level is the fastest way to lose a credible listener.

---

## 3. Data sources & caveats

| Source | Gives you | Caveat |
|---|---|---|
| **FotMob** (JSON endpoints) | **the productivity + minutes layer** — goals, assists, apps, started, **minutes played** per player per season + match-by-match; confirmed for SL2 / League One / Championship | undocumented Next.js JSON endpoints — plain-Python readable (no headless browser), but they can change; rate-limit politely |
| Transfermarkt | the **market + availability** layer — free-agent flags, contract expiry, market value, squad lists | squad pages scrape fine; **its per-player *performance* page no longer uses table markup (div/JS) — do NOT source minutes from TM, use FotMob** |
| `cesc-football-scraper` (pip) | wrapper over FotMob/TM/Understat/Sofascore/ESPN | third-party; verify coverage per league, but a fast start |
| `worldfootballR` (R) | mature Transfermarkt support (`tm_*` functions) | R, not Python — the most reliable TM route for market data |
| SPFL official site | authoritative SL2 apps/goals | SL2 only |
| Released / retained lists (club sites, BBC) | who's actually becoming available each May/June | unstructured prose → **LLM-parse into structured rows** |
| Local news / forums / socials | availability rumours, injury/attitude signal | noisy → LLM extraction, treat as soft signal |

**Join model:** FotMob (stats) ↔ Transfermarkt (market) matched on player name + DOB. Prior art exists — public 2025/26 club recruitment dashboards pair FotMob + TM scrapers exactly this way — so the two-source design is proven, not speculative.

**Legal/ethical note (not legal advice):** respect robots.txt and rate limits, prefer maintained wrappers over raw scraping, cache aggressively, and don't redistribute the raw data. This is public-interest recruitment research, but keep it low-impact and clean.

---

## 4. Player data schema

| Field | Source | Notes |
|---|---|---|
| `player_id`, `name` | Transfermarkt | stable id for dedup across leagues |
| `age`, `dob` | TM | age curve matters a lot at this level |
| `position`, `sub_position` | TM | broad role for equivalency + matching |
| `height`, `foot` | TM | physical proxy (thin but useful) |
| `current_club`, `league`, `league_tier` | TM | for league-equivalency lookup |
| `apps`, `minutes` (per season) | TM/SPFL/FotMob | durability + per-90 denominator |
| `goals`, `assists` (per season) | TM/SPFL | raw output |
| `market_value` | TM | affordability proxy |
| `contract_expiry` | TM | availability signal |
| `availability_status` | derived + LLM | free / expiring / released / loan-candidate / feeder |
| `league_adj_output` | computed | §5 — the key derived feature |
| `role_archetype` | computed | §7 clustering |
| `success_similarity` | computed | §7 |
| `affordability_est` | computed | §7 |
| `shortlist_score`, `flags`, `reason` | computed/LLM | §8–9 |
| `status`, `notes` | human | HITL queue |

---

## 5. The analytical core: cross-league equivalency

**The problem:** your pool spans SL2, Highland, Lowland, junior/non-league, and lower Irish/English tiers. 20 goals in the Highland League ≠ 15 in SL2. With no advanced data to judge quality directly, raw counting stats *lie* unless corrected for the league they were produced in. Uncorrected, the tool just recommends whoever scored most in the weakest league.

**The method — league-equivalency coefficients** (the same idea as hockey league translations, runs entirely on free transition data):

1. **Collect transitions.** Find players who moved *between* the target leagues over the last ~5–6 seasons (Highland→SL2, SL2→League One, non-league→SL2, LOI→SL2, etc.), with enough minutes on both sides of the move.
2. **Measure the output change.** For each mover, compute output rate (goal contributions per 90, or per appearance if minutes are missing) in the season(s) before vs after.
3. **Aggregate into a coefficient.** For each league pair A→B, the coefficient ≈ median( rate_in_B / rate_in_A ) across movers, weighted by minutes. Use median (or a light regression) to blunt noise.
4. **Anchor to SL2 = 1.0.** Express every league on an SL2-equivalent scale. A Highland coefficient of, say, ~0.6 means output there deflates to ~60% when translated to SL2.
5. **Chain sparse pairs.** Where a direct A→SL2 sample is too thin, chain through an intermediate league with better sample (A→B→SL2).

Then `league_adj_output = raw_output × coefficient(player_league → SL2)`.

**Be honest about the biases (design around them, state them):**
- **Survivorship bias** — you only observe players *good enough* to earn the move, which inflates lower-league coefficients. Acknowledge it; treat coefficients as ranges, not point truths.
- **Age confound** — young movers improve naturally, muddying the ratio. Filter to a stable age band or model age separately.
- **Position effects** — compute per broad position (a defender's "output" isn't goals). For non-attackers, lean on minutes/apps and disciplinary rate as thin proxies, and flag that the metric is weaker.
- **Small samples per pair** — the whole Scottish pyramid is small; some pairs will have few movers. Report the sample size behind each coefficient so a human knows how much to trust it.

This equivalency layer is the genuinely interesting, defensible piece — a real method solving a real problem on free data, and a strong portfolio talking point precisely because it's honestly scoped.

---

## 6. Defining "proven SL2 success"

Build target profiles from what's visible:
- **Output:** league-adjusted goal contributions above a percentile threshold over a minimum appearance count.
- **Durability & trust:** high minutes/appearance share (the manager kept picking them).
- **Recognition:** Player of the Month/Year, promotion-winning squads.
- **Step-up validation (strong signal):** players who went SL2→League One *and stuck* — proof the SL2 output was real.

Cluster the *successful* SL2 players into role archetypes (§7); each archetype's centroid becomes a target profile to match against.

---

## 7. Availability pools, features & matching

**Availability pools (the coverage edge):**
- **Free agents** — Transfermarkt "without club" flag.
- **Out-of-contract soon** — expiry within 6–12 months.
- **Released/retained** — parsed from May/June lists via LLM.
- **Inferred loan candidates** — young players (≈U21–U23) at Premiership/Championship/League One clubs with *low minutes share* → buried talent likely available to loan. Compute minutes% vs squad; flag the buried ones.
- **Feeder leagues** — Highland, Lowland, junior/non-league, lower Irish/English tiers.

**Feature vector (per player):** league-adjusted per-90 output (position-appropriate), age, appearance/minutes durability, position, height/foot, level trajectory (history of tiers played). Normalise.

**Matching:**
1. Cluster into **role archetypes** (k-means or HDBSCAN) so you compare like with like.
2. For each available player, compute **similarity** (cosine/euclidean) to the SL2 success-profile centroid(s) for their archetype → `success_similarity`.
3. **Affordability filter:** proxy expected wage from age + level + market value; free/loan status raises feasibility. Drop the unrealistic.
4. **Shortlist score** = success_similarity × availability_feasibility × affordability_fit, with league-adjusted output as the dominant input. Rank.

Nearest-neighbour on a thin feature vector — **not deep learning, and don't call it that.** Classical similarity is the correct tool for this data size.

---

## 8. The shortlist (HITL queue)

Ranked, filterable by position/pool/age/affordability. Each row expands to show:
- **League-adjusted stats** next to the raw ones (so the human sees the translation).
- **Who they resemble** — named SL2 successes / the archetype ("profiles like a proven SL2 target man").
- **Availability** — free / expiring / loan-candidate, with source.
- **Affordability estimate** — a realistic band, with reasoning.
- **Flags** — small sample, weak-position-metric, age risk, injury/attitude signal from the LLM pass.

Human sets status (watch / contact / trial / signed / passed) + notes. Those logged outcomes become the V3 feedback signal.

---

## 9. Validation (harder here — be upfront)

"Would this player have succeeded?" is counterfactual, so validation is genuinely harder than the sponsor tool. The honest check is **retrospective**:

- Take players SL2 clubs actually signed in past windows who worked out. Reconstruct the available pool *at that time*. Check whether the tool would have surfaced them near the top. Report precision@k / recall@k.
- Sanity-check the equivalency coefficients against known step-ups (did players the model rates highly actually progress?).

State the limits plainly: small samples, survivorship bias, and no capture of character/physicality mean this is **decision support, not prediction**. A human checks every row. That honesty is more credible than a false precision claim.

---

## 10. Honesty flags (bake into the UI, not just the pitch)

- **Tiny numbers:** SL2 is 10 teams, 36 games — 16 goals vs 13 is largely noise. Show outputs as directional bands, not decimals-of-false-precision.
- **Style blindness:** a poacher and a link-up forward both just "score goals" in counting data — the tool can't tell them apart. Flag it; that's the human's job (and Wyscout's, later).
- **Non-attackers are weaker:** defenders/midfielders lack good free output metrics; label their scores lower-confidence.

---

## 11. Build sequence

**V1 — strikers only, proof of method.** Attackers are where counting stats mean the most, so prove the pipeline there: data pull → league-equivalency coefficients → SL2 success profile → similarity match → affordability filter → ranked shortlist into the queue. A single-position, honestly-scoped V1 is a legitimate deliverable.

**V2 — all positions + coverage.** Role clustering across positions, LLM parsing of released lists and availability signal, the affordability model, loan-candidate inference.

**V3 — upgrade + learning loop.** Plug in Wyscout if the club gets access (richer features into the same pipeline); and once real outcomes are logged (surfaced → signed → performed), fold them back to refine profiles and weights.

---

## 12. Suggested stack

Python; `soccerdata` (and/or `worldfootballR` via R) for Transfermarkt/FotMob; `pandas`; `scikit-learn` + `hdbscan` for clustering/similarity; a small regression for the equivalency coefficients; an LLM API for parsing released lists and availability chatter; outputs to the same Google Sheet / Airtable queue as the other tools. Keep the target-league set, equivalency coefficients, and thresholds in config so they're tunable without code changes.

---

## 13. Where the genuine AI/ML sits (say it plainly)

- **Classical ML:** the similarity matching, the role clustering, and the regression behind the equivalency coefficients. This is the honest core.
- **Genuine (modest) AI:** the LLM turning unstructured released-lists, news, and forum chatter into structured availability data — a real NLP job, not decoration.
- **Deep learning:** honestly, **none needed in V1** — the data is small and tabular, so classical methods are correct and claiming a deep net here would be a red flag, not a selling point. (If scouting-report *text* becomes available later, text embeddings could help match on playing style — a legitimate future addition, not a V1 claim.)
- **Not AI:** the scraping, the affordability proxy, and the final ranking arithmetic — solid data engineering that makes the analytics usable.

The intelligence is in the design: the league-equivalency layer makes cross-league comparison honest, systematic coverage of the availability pool is the actual market edge, and the human-in-the-loop shortlist keeps the tool on the right side of what free data can and can't know.

---

## 14. Future direction — causal inference (noted, not V1)

The league-equivalency step (§5) is, strictly, a **causal estimation problem**, and the current literature says so: recent work modelling performance change after a league move concludes its league coefficients stay *associative rather than causal* because players who move up are **selected, not randomly sampled** — the exact survivorship bias flagged in §5. So causal methods aren't a bolt-on; they're the principled fix for a bias already in the design. In rough order of ambition and data-hunger:

- **V2-realistic — sharpen the coefficients with a causal design.** Replace the naive before/after output ratio (which conflates the move with ageing, development, and a new team) with **difference-in-differences**: compare movers' output change against a control group of comparable players who *didn't* move, isolating the league-change effect. Or a **hierarchical Bayesian model** that explicitly separates league, team, and age effects (the approach serious practitioners now use). Both are feasible on the counting + transition data already planned.
- **The North Star — the actually-causal recruitment question.** "Will this player make *us* better?" is a counterfactual/intervention question, not "is this player good?" Frontier methods (Estimated Player Impact via mixed models, adjusted plus-minus) isolate a player's contribution net of teammates, tactics, and opposition — but they need **event-level data**, i.e. Wyscout-era. Genuinely future; SL2's free-data floor can't support it.

Framing the equivalency step as selection-biased and naming the causal design that addresses it signals command of the frontier top clubs are working on — without overclaiming what fourth-tier data can bear.
