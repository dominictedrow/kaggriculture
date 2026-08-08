# One-Time Crops (Wheat/Carrot/Melon) -- Findings

Domain under test: crop mix, planting density, watering/fertilizing discipline,
harvest timing, land-expansion timing, and sell batching for wheat, carrot,
and melon. Agent code is config-driven (`engine.py::make_agent`); every
combination below is the *same* code with different config dict values --
see config key meanings at the bottom of `engine.py`.

## Method

Two-phase sweep:
- Phase 1 (screen): 8 crop mixes x 6 tile densities (4/8/12/16/20/25) = 48
  configs, sane defaults (harvest at first_yield_day, never fertilize, never
  expand land, dump-sell, no hired hands). See `phase1_screen.json`.
- Phase 2 (screen): for the strongest Phase-1 survivors, one-dimension-at-a-
  time variations -- harvest timing (first vs max), fertilizing, land
  expansion x hiring (paired, since expansion is wasted without hands to work
  it), and sell batching. 42 configs, see `phase2_screen.json` /
  `extra_screen.json`.
- Phase 3 (confirm): top 20 by screening score, full scale -- n=30 episodes
  per opponent x (random, starter) x episode_steps=720 (60 episodes each).
  These are the only numbers below that count as leaderboard entries. See
  `results/confirm.json`.

Every config sells via `SELL <crop> <shed_qty>` (dump) or only once shed_qty
crosses a batch threshold of 20 (`sell=("batch", 20)`); ranking metric is
`combined = 0.5 * mean(vs random) + 0.5 * mean(vs starter)`.

## Confirmed leaderboard (n=30/opponent, episode_steps=720)

| # | Config | Combined | vs random | vs starter |
|---|---|---|---|---|
| 1 | melon-mono, mt=50, land=[10], hire=1 | **27528** | 27529 | 27527 |
| 2 | melon-mono, mt=50, land=[8,15,20], hire=1 | 23651 | 23627 | 23675 |
| 3 | melon-mono, mt=20, no land/hire | 19646 | 19644 | 19649 |
| 4 | melon-mono, mt=12, no land/hire | 19183 | 19164 | 19202 |
| 5 | melon-mono, mt=25, no land/hire | 19044 | 19022 | 19065 |
| 6 | melon-mono, mt=16, no land/hire | 17711 | 17719 | 17703 |
| 7 | melon-mono, mt=20, sell batch(20) | 17103 | 17096 | 17109 |
| 8 | melon-mono, mt=25, sell batch(20) | 16505 | 16507 | 16504 |
| 9 | melon-mono, mt=50, land=[10], no hire | 16375 | 16246 | 16504 |
| 10 | melon-mono, mt=12, sell batch(20) | 16266 | 16258 | 16274 |

Full 20-entry confirmed set (incl. wheat-melon and carrot-melon mixes, all
weaker than melon-mono) is in `results/confirm.json`; screening-only data
(configs never promoted to n=30 confirmation) is in `phase1_screen.json` /
`phase2_screen.json` / `extra_screen.json` and does not count as a
leaderboard entry per the n>=30 rule.

## Top result, exact reimplementable rule (#1, $27,528)

**Melon monoculture, single farmer + 1 hired hand, buy exactly the land you
plan to use.**

- Tile plan: fill up to 50 tiles with MELON, scanning NW quadrant fully (25
  cells) then NE quadrant (25 cells), in fixed row-major order. Never touch
  SW/SE.
- Every turn, for the farmer and the 1 hired hand independently:
  1. If standing on an empty plan tile and you hold a MELON seed -> `PLANT MELON`.
  2. If standing on a WEED -> `DIG`.
  3. If standing on a MELON plant, `age = day - planted_day`:
     - If `age >= 10` (melon's `first_yield_day` == `max_yield_day`, both 10)
       and `yield_units > 0` -> `HARVEST`. Daily watering through this point
       already banks the full 6-unit cap (base 1 + 1/watered-day from age 6
       through age 10 -- see RULES.md's melon bonus-window note), so there is
       no benefit to fertilizing or waiting past day 10.
     - Else if not watered today -> `WATER`.
  4. Otherwise, step one tile toward the nearest plan tile that still needs
     an action (Manhattan-nearest).
- Seed buying: every turn, `BUY_SEED MELON n` for however many plan tiles are
  currently empty and unseeded ($80/seed).
- Selling: every turn, `SELL MELON <entire shed quantity>` (dump-immediate;
  melon's base price is $250 and this fixed-small-farm volume never gets
  close to crashing its own price).
- Land: on **day 10 only**, if `money >= $1200` ($1000 cost + buffer), issue
  `BUY_LAND` once (unlocks NE, taking density from 25 tiles to 50).
- Hiring: every day at hour 0, issue exactly one `HIRE` (costs `1 x fib(0) =
  $1` for the first hire of the day, since hire count resets daily).

**Why it wins:** melon has by far the best $/tile/day of the three one-time
crops once you account for its price ($250 base vs $25/$35), and critically
its unfertilized max yield (6 units) is reached by day 10 *simultaneously*
with its first eligible harvest day -- so simple daily watering + immediate
harvest already captures the maximum possible yield, no fertilizer logistics
needed. #2 shows that buying land you can't use is a net loss: it also
expands to SW/SE (days 15, 20) but caps planting at the same 50 tiles, so it
pays $6,000 more in land ($2k+$4k) for zero extra usable tiles and nets
$3,877 less than #1.

## Runner-up mechanism: single-farmer density ceiling (#3-6)

With **no land expansion and no hired hand**, melon-mono peaks around
**mt=12-20** (~$19-19.6k) and *degrades* past mt=25 (~$19.0k) and below
mt=8-16. A lone farmer has 24 turns/day to walk, water, harvest, and replant;
past ~20 tiles the daily circuit is too long to revisit every plant before it
misses a watering, so higher density stops helping and starts costing
(missed waterings -> lower yield or occasional weed conversion). Reimplement
as: same rule set as #1 but `max_tiles=16-20`, no `BUY_LAND`, no `HIRE`.

## What didn't help

- **Fertilizing** (`fertilize="bonus"` + `harvest_at="max"`) on wheat/carrot
  mixes scored far worse in Phase 2 screening (roughly half the un-fertilized
  equivalent) -- the extra `PICKUP`/`FERTILIZE` actions and fertilizer
  purchase cost outweigh the yield bonus at this scale; not promoted to
  confirmation.
- **Sell batching at 20** consistently underperformed dump-immediate for the
  same density/land/hire settings (e.g. mt=20: 17103 batched vs 19646 dump)
  -- melon's price curve absorbs this farm's small sell volume fine, so
  holding inventory only delays cash you could already be reinvesting.
- **Wheat-melon and carrot-melon mixes** all confirmed below pure melon-mono
  at equivalent density -- diluting tile allocation away from melon (the
  best $/tile crop) with a cheaper crop is a net loss here.
