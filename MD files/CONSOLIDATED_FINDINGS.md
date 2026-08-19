# Kaggriculture Strategy Search -- Consolidated Findings

Four parallel research passes tested strategies across crops, livestock,
market tactics, and labor/land economics. This document merges all four into
one ranked picture and calls out the mechanisms behind what worked. Full
detail (every config tested, complete leaderboards, raw JSON) lives in each
domain's own `strategies/<domain>/FINDINGS.md`.

**Important caveat on comparing across domains:** crops and livestock each
optimized their *entire* production choice, so their numbers are directly
usable as standalone strategies. Market and labor/land deliberately held
production fixed and small (a 12-tile wheat/carrot loop, or a single-crop
wheat loop) so their numbers isolate the effect of the sell-tactic or
hire/land-tactic layer -- **their absolute money is not competitive with
crops/livestock and shouldn't be read as "market tactics are weak."** Read
market and labor/land as tactics to graft onto a strong production plan
(like crops' melon-mono), not as competing standalone strategies.

## Overall ranked table (best confirmed result per domain)

| Rank | Domain | Best config | Combined $ | n | vs random | vs starter |
|---|---|---|---|---|---|---|
| 1 | **Livestock** | 4 COW + 2 SHEEP, 2 hands | **50316** | 30/opp | 50652 | 49980 |
| 2 | **Crops** | Melon-mono, 50 tiles, +1 land, 1 hand | **27528** | 30/opp | 27529 | 27527 |
| 3 | Labor/land (fixed wheat-loop task) | Flat 4 hands/day, never buy land | 12157 | 30/opp | 12301 | 12012 |
| 4 | Market (fixed 12-tile wheat+carrot task) | Wheat: gate at $20; carrot: dump | 5971 | 30/opp | -- | -- |

All four ran with `episode_steps=720` (the full 30-day season) and
`startingMoney=3000`. "Combined" = `0.5 * mean(vs random) + 0.5 * mean(vs
starter)`, agent's own final money (not win/loss).

## The single best strategy: livestock (4 cows + 2 sheep + 2 hands, $50,316)

This beat crops' best result by ~83%, which was the biggest surprise of the
search -- livestock's payoff-per-dollar-invested turned out to exceed even
melon (the strongest crop). The exact rule:

- Buy 4 COW ($400 each) + 2 SHEEP ($500 each) as early as affordable, no
  delay, no per-day buy cap. Total roster cost ~$2,600 out of the $3,000
  starting bank.
- Build a PASTURE on each of the 6 assigned tiles (both cow and sheep use
  pasture; no coop needed -- goose was tested and was the weakest animal by
  a clear margin).
- Feed every animal every day without fail, care every day without fail
  (banks `pending_care_bonus`, paid out whole on the next scheduled
  production tick -- free money for one extra action/day).
- Harvest milk/wool the instant `yield_units > 0`; collect fertilizer
  whenever available; sell every non-wheat shed item immediately, every
  turn.
- Buy wheat to exactly cover the day's feed need (6 units/day), no slack
  buffer -- excess wheat purchases are pure cost.
- Hire 2 extra hands every day (all 6 animals fit in the always-unlocked NW
  quadrant, so **zero land purchases needed** -- the entire strategy runs
  on the starting 25 tiles).

Full pseudocode and the mechanism discussion (why 4:2 beats 6:0 and 3:3, why
2 hands beats 1) is in `strategies/livestock/FINDINGS.md`.

## Runner-up: melon monoculture ($27,528)

- Fill up to 50 tiles (NW + NE quadrants) with MELON, single farmer + 1
  hired hand.
- Water daily, harvest at day 10 (melon's `first_yield_day` and
  `max_yield_day` are both 10, so simple daily watering already banks the
  full 6-unit cap with zero fertilizer needed).
- Buy the NE quadrant ($1,000) on day 10 -- and *only* the land you'll
  actually plant on. A variant that also bought SW+SE ($6,000 more) scored
  $3,877 lower for zero extra usable tiles, since planting density stayed
  capped at 50 either way.
- Sell melon dump-immediate every turn (base price $250, this farm's volume
  never gets close to crashing it).
- Hire exactly 1 extra hand every day.

Full leaderboard and the single-farmer density-ceiling finding (a lone
farmer without hands peaks around 12-20 melon tiles, not higher) is in
`strategies/crops/FINDINGS.md`.

## Tactical layers to graft onto either strategy

These didn't get tested standalone at competitive scale, but their
*mechanism* transfers directly onto a bigger farm:

**From labor/land** (`strategies/labor_land/FINDINGS.md`): marginal hand ROI
on a fixed task peaked at 4 hands and turned negative past 6 (crowding on a
25-tile quadrant); land expansion was a net loser in every tested case
except buying the next quadrant once utilization crosses 80%. This directly
explains why livestock's winning config topped out at 2 hands on a 6-animal
roster, and why crops' winner bought exactly 1 quadrant, not 3.

**From market** (`strategies/market/FINDINGS.md`): wheat's price curve
absorbs oversupply cheaply, so dump-immediate (or a mild $20 price floor) is
fine for wheat. Carrot's price curve craters hard on oversupply -- gate or
batch carrot sales (threshold >=10 units, or price_gate >=$25-30) rather
than dumping. This same asymmetry applies to melon and milk/wool: RULES.md's
price table shows melon, strawberry, milk, and wool are *all* premium goods
with `above_target > 1` (crash-to-floor-on-glut), the same shape as carrot,
so the winning livestock and crops strategies (which dump-sell every turn at
this farm's *volume*) would likely benefit from the same gating logic if
scaled up further -- worth testing before finalizing, since neither the
crops nor livestock sweep varied sell tactics at all (that dimension was
deliberately market's job, and market tested it on a much smaller farm than
either winner).

**Untested combination worth trying:** livestock's winning 6-animal roster
only uses 6 of the NW quadrant's 25 tiles. Nothing in the livestock sweep
planted crops on the other 19 -- a combined build (livestock on 6 tiles +
melon on the rest, one farmer + hired hands split across both) was never
tested and could plausibly beat either domain's isolated number, since no
resource conflict exists (different tiles, and both use wheat only as a
minor input cost).

## Completeness notes

- **Crops**: 90 configs tested (48 screen + 42 screen-2), 20 confirmed at
  full n=30/opponent/720-step scale.
- **Livestock**: ~30+ configs across two screening passes, 17 confirmed at
  full scale.
- **Labor/land**: 81 configs tested, 20 confirmed at full scale (includes a
  12-pair tile-allocation supplement).
- **Market**: 65 configs screened, 19 of 20 intended confirmations completed
  at full scale (the 20th, a lower-screening-score config, was not reached).

All "leaderboard" numbers cited above and in the per-domain files are from
the n>=30-episodes-per-opponent confirmation phase, not screening-only runs.
