# How the shortlist scores are worked out

A plain-language guide. No maths background needed.

---

## The one-sentence version

Every available player gets a **shortlist score between 0 and 1**. It answers a single question: *how good a recruit is this player for Dumbarton, all things considered?* Higher is better, and the list is simply sorted from highest to lowest so the human starts at the top.

That single number is built from **three things multiplied together**:

> **shortlist score = how well they fit × how gettable they are × how affordable they are**

We multiply (rather than add) on purpose: if any one of the three is zero, the score is zero. A perfect fit you can't sign, or can't afford, is not a real recruit — and multiplying makes the maths agree with common sense.

Before any of that can happen, though, we have to make players from different leagues comparable. That's step zero, and it's the clever part.

---

## Step 0 — Make everyone comparable (the "exchange rate")

Goals in a weak league aren't worth the same as goals in a strong one. If we ranked players on raw numbers, we'd sign whoever scored most against the worst defences. So first we convert every player's output onto one common **"SL2-equivalent" scale**, like converting foreign currencies into pounds.

How we get the exchange rate, cheaply: we watch players who **actually moved** between leagues and see how their output changed. If strikers moving from the Highland League to SL2 typically see their scoring drop to about two-thirds, then the Highland "exchange rate" is about **0.67**. SL2 itself is the reference point, fixed at **1.0**.

Then, for every player:

> **adjusted output = raw output × their league's exchange rate**

- A Highland striker with a raw **0.74** goal-contributions per 90 → **0.74 × 0.70 ≈ 0.52** once translated. His gaudy number shrinks.
- A League One striker with a raw **0.35** → **0.35 × 1.30 ≈ 0.46**. His modest number *grows*, because doing it in a tougher league counts for more.

Everything after this uses the **adjusted** number, never the raw one.

---

## Step 1 — What does "proven SL2 success" look like?

We build a **target profile** from strikers who genuinely did the job in SL2: strong adjusted output, plenty of minutes (the manager kept picking them), and not too old. We average those players together to get one profile, e.g.:

> the typical successful SL2 striker: **~0.61 adjusted output/90, age ~24, ~2,300 minutes a season**

That profile is the yardstick every available player is measured against.

---

## Step 2 — "How well they fit" (similarity)

For each available player we compare three features to the profile — **adjusted output**, **age**, and **minutes/durability** — and turn the gap into a score between 0 and 1, where **1 = a perfect match** for the profile and lower means further away.

Two sensible rules are baked in:

- **Output and durability: only being *worse* counts against you.** If a player is *better* than the average SL2 success, that's a good thing, not a penalty. We only dock points when they fall short.
- **Age counts both ways.** Too old is a risk; too young is unproven. Either direction moves them away from the profile.

Output matters most, so it carries the biggest weight (roughly 60%), with age and durability making up the rest. These weights are visible in the code and easy to tune.

---

## Step 3 — "How gettable they are" (availability)

A player is only useful if you can actually sign him. Each availability type gets a feasibility value:

| Situation | Feasibility |
|---|---|
| Free agent (no club) | 1.0 |
| Contract expiring soon | 0.7 |
| Young player buried at a bigger club (loan candidate) | 0.6 |
| Under contract, settled | 0.0 (filtered out) |

Contracted players who aren't going anywhere are dropped before scoring — no point ranking players you can't get.

---

## Step 4 — "How affordable they are" (affordability)

We estimate a realistic weekly wage from the player's level, market value, and age, then compare it to a notional small-club budget. If the estimate is **within budget**, affordability = 1.0. If it's **over**, the score tapers off the further above budget it goes. Free agents get a small break, since there's no transfer fee.

This is deliberately a rough proxy, not a real contract — it exists to stop the list recommending players who are financially out of reach.

---

## Putting it together — a worked example

Say an available **free-agent striker** comes back with:

- fit (similarity) = **0.90**
- availability (free agent) = **1.0**
- affordability (within budget) = **1.0**

> score = 0.90 × 1.0 × 1.0 = **0.90** → near the top of the list.

Now a slightly better *fit* but harder to get:

- fit = **0.96**, but availability (expiring, not free) = **0.7**, affordability = **1.0**

> score = 0.96 × 0.7 × 1.0 = **0.67** → still good, but ranked below the free agent.

That's the trade-off the score is designed to capture: a slightly worse fit you can sign today beats a marginally better one you might not.

---

## What the score is — and isn't

- It's a **prioritisation aid**, not a verdict. It puts the most promising, gettable, affordable options at the top so a human spends time on the right names.
- **A person makes every call.** The tool can't see character, attitude, injuries, or how a player fits the dressing room — exactly the things that decide signings at this level. Those are the human's job.
- **Flags travel with each row** — "small sample," "age risk," "big translation" (a large weak-league adjustment) — so the reader knows where to be cautious.
- The numbers are **directional, not precise.** SL2 is a small league; treat a 0.90 vs 0.88 as "both strong," not "one is clearly better."

In short: the score does the heavy lifting of comparing players fairly and surfacing realistic options — and then it gets out of the way and lets a person decide.
