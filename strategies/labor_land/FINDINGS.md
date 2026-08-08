# Labor & Land Economics -- Findings

Domain under test: farm-hand hiring cadence and land-purchase timing. The
market/crop/livestock choice itself is deliberately held fixed and simple
(see below) so every result here isolates the effect of the
hiring/expansion policy layered on top.

## Fixed production task (identical in every config below)

Every active unit -- the main farmer plus any hired hands -- runs the same
**wheat loop** independently, on whichever tile it is nearest to within its
assigned tile list:

1. Standing on a WHEAT plant with `age >= 4` (`max_yield_day`) -> `HARVEST`
2. Standing on a WHEAT plant not watered today -> `WATER`
3. Standing on a WEED -> `DIG`
4. Standing on an empty tile with a WHEAT seed available -> `PLANT WHEAT`
5. Otherwise, take one step toward the nearest tile in its assigned list
   that needs one of the above (priority: harvest > water > dig-weed >
   plant, ties broken by Manhattan distance)
6. If nothing in its list needs anything, `PASS`

Market side, every turn: sell all WHEAT sitting in the shed, and top up the
WHEAT seed stock to `n_active_units` (farmer + hands) so a unit is never
blocked from planting the instant it reaches an empty tile (the engine
validates `PLANT` against the seed pool as of the *start* of the turn, so
the buffer has to be pre-funded a turn ahead; topping up every turn keeps it
full from turn 2 onward).

**Tile allocation** (which unit works which tile) is itself one of the
tested dimensions, not part of the fixed task:
- `stripe` (default): all currently-unlocked tiles, row-major order, split
  `tile[i] -> unit[i % n_units]`.
- `quadrant`: tiles grouped by quadrant (NW/NE/SW/SE), whole quadrants
  handed to units round-robin.
- `nearest`: no fixed assignment; each unit (farmer first, then hands in
  order) greedily claims the closest tile in the full unlocked pool that
  still needs work that turn, removing it from the pool for the next unit.

A 12-pair supplementary screen (top 6 hiring/land configs x quadrant and
nearest) found stripe beats both alternatives on every config tested
(stripe about 5400 vs nearest about 5150 vs quadrant about 4100 in
screening units) -- see `results/allocation_screen_results.json`. All
confirmed leaderboard entries below use `stripe`.

## Method

Two-phase sweep (`sweep.py`, parallelized across configs with
`multiprocessing.Pool`):

- Phase 1 (screen): all 69 base configs, n=8 episodes per opponent x
  (random, starter) x episode_steps=300. Ranked by
  0.5 * mean(vs random) + 0.5 * mean(vs starter).
- Allocation supplement: top 6 screening survivors re-screened under
  quadrant/nearest (12 more runs) -- stripe won every one, so it carries
  forward as-is (see above).
- Phase 2 (confirm): top 20 configs by screening score, full scale --
  n=30 episodes per opponent x (random, starter) x episode_steps=720
  (60 episodes each). These are the only numbers below that count as
  leaderboard entries.

81 distinct (hire policy x land policy x allocation) configurations were
run in total across both phases; 20 were confirmed at full scale. Raw JSON
for every run is in `strategies/labor_land/results/`.

## Confirmed leaderboard (n=30/opponent, episode_steps=720)

Ranked by combined = 0.5 * mean(vs random) + 0.5 * mean(vs starter), agent's
own final money.

| # | Config | Hire policy | Land policy | Combined | vs random (mean/median/sd) | vs starter (mean/median/sd) |
|---|---|---|---|---|---|---|
| 1 | A_hire_flat4_noland | flat(4) | never | 12157 | 12301 / 11675 / 1424 | 12012 / 11238 / 1278 |
| 2 | A_hire_fibcap3_noland | fib-cap(3) | never | 12037 | 12008 / 11165 / 1238 | 12066 / 11302 / 1288 |
| 3 | A_hire_fibcap5_noland | fib-cap(5) | never | 11942 | 11780 / 11479 / 1399 | 12104 / 11964 / 1383 |
| 4 | A_hire_flat5_noland | flat(5) | never | 11760 | 11961 / 11636 / 1377 | 11559 / 10821 / 1454 |
| 5 | A_hire_ramp_0_10_0_6_noland | ramp day0-10, 0 to 6 | never | 11090 | 11097 / 11285 / 1567 | 11083 / 11316 / 1492 |
| 6 | C_flat4_util80 | flat(4) | util-gate(0.8) | 11087 | 10827 / 10584 / 1070 | 11346 / 11280 / 1069 |
| 7 | A_hire_flat6_noland | flat(6) | never | 11045 | 11273 / 11428 / 1190 | 10816 / 10528 / 1168 |
| 8 | A_hire_fibcap13_noland | fib-cap(13) | never | 10929 | 10842 / 10152 / 1370 | 11017 / 10134 / 1418 |
| 9 | E_flat8_noland_crowding | flat(8) | never | 10796 | 10820 / 10236 / 1406 | 10772 / 10690 / 1006 |
| 10 | A_hire_flat8_noland | flat(8), dup of #9 | never | 10657 | 10733 / 10034 / 1482 | 10581 / 9927 / 1297 |
| 11 | A_hire_flat3_noland | flat(3) | never | 10319 | 10160 / 10286 / 990 | 10478 / 10431 / 950 |
| 12 | A_hire_day5_2_noland | 2 hands from day5 | never | 9831 | 9858 / 10136 / 1026 | 9804 / 10108 / 1183 |
| 13 | A_hire_scaleland2_noland | 2 hands/quadrant | never | 9562 | 9538 / 9703 / 943 | 9586 / 10068 / 1063 |
| 14 | A_hire_fibcap1_noland | fib-cap(1) | never | 9485 | 9668 / 9625 / 843 | 9303 / 9390 / 982 |
| 15 | C_flat2_util90 | flat(2) | util-gate(0.9) | 9448 | 9404 / 9422 / 999 | 9492 / 9499 / 868 |
| 16 | A_hire_money2k_2_noland | 2 hands at $2000+ | never | 9427 | 9460 / 9406 / 778 | 9394 / 9546 / 785 |
| 17 | A_hire_day0_2_noland | 2 hands from day0 | never | 9361 | 9289 / 9288 / 978 | 9432 / 9549 / 1032 |
| 18 | A_hire_flat2_noland | flat(2) | never | 9261 | 9376 / 9389 / 985 | 9145 / 8933 / 1048 |
| 19 | E_flat4_land_day14 | flat(4) | buy at day>=14 | 5409 | 5340 / 4808 / 1357 | 5477 / 5133 / 1284 |
| 20 | C_fibcap5_money6000 | fib-cap(5) | buy at $6000+ | 3883 | 3956 / 3508 / 1122 | 3810 / 3419 / 1118 |

(#9/#10 are two independently-named configs that happen to encode the
identical policy, flat(8) + never-expand; their about 1.3% score gap is
pure run-to-run sampling noise and a useful informal error bar on these
numbers.)

## Headline finding: land expansion loses money under this task

Every one of the top 18 confirmed entries never buys land (stays on the
starting NW quadrant, 25 tiles) or only buys it very late/conservatively.
Every config that expands early or aggressively (E_flat4_land_day14,
C_fibcap5_money6000, and in screening: immediate, day3, money1500,
money3000 land policies) lands far below the no-land baseline -- roughly
5.4k or 3.9k confirmed vs. 9.3k-12.2k for staying on NW. In screening,
every aggressive land policy scored 1200-3300 vs. about 4300-5400 for
comparable no-land or barely-gated policies (results/screen_results.json).

Why, given this specific fixed task: (1) each BUY_LAND costs real cash
(1000/2000/4000) that is otherwise going straight into hiring/seed buffer,
and buying NE+SW back-to-back burns the entire 3000 starting stack before
any wheat has sold; (2) the stripe/quadrant allocation immediately spreads
the existing hand count over the newly-unlocked tiles too, so adding land
without first having spare hands to match dilutes everyone's attention
rather than adding net throughput. The one exception that worked is
C_flat4_util80 (#6): it holds a stable 4 hands and only buys the next
quadrant once utilization (occupied/unlocked tiles) crosses 80 percent --
i.e., only once NW is already nearly saturated by the existing labor force.
That is the only land-buying config that reached the top tier.

This is a property of the fixed wheat-loop task (a 10-cost-seed, about
20-45 sell-price crop with a 5-day cycle, in a 30-day season) combined with
stripe/quadrant allocation that always redistributes evenly across all
unlocked tiles regardless of headcount -- not a claim that land is
worthless in general. A higher-value crop, a longer season, or an
allocation rule that keeps new hires working old land until they are
genuinely needed on new land could change this. Read every result here as
"...under this fixed low-value quick-cycle task."

## Top entries: exact, reimplementable rules

Pseudocode below is exact -- Dom should be able to reimplement any of these
from this section alone. n_hires_target(day, hour, money, hires_today,
n_quadrants, utilization) is evaluated every turn; the agent issues HIRE
market orders until hires_today reaches the returned target (capped by
the 10-orders-per-turn limit, retried on later turns if capped). Hand
count resets to 0 every day (hires must be redone daily) so these targets
are re-applied fresh each day.

**#1 -- flat(4), never expand.** Every day, hire hands until you have
exactly 4 (main farmer + 4 hands = 5 units total working NW's 25 tiles).
Hiring cost sequence per day: hand 1 = 1, hand 2 = 1, hand 3 = 2, hand 4
= 3 (fib(0..3)), total 7/day. Never issue BUY_LAND. Each unit runs the
wheat loop above, split stripe-style: sort all 25 NW tiles row-major,
tile[i] is worked by unit[i mod 5].

**#2 -- fib-cap(3), never expand.** Equivalent in practice to #1: hire
the next hand as long as its fib cost would be <= 3. fib(0)=1<=3 (hire
1st), fib(1)=1<=3 (hire 2nd), fib(2)=2<=3 (hire 3rd), fib(3)=3<=3 (hire
4th), fib(4)=5>3 (stop). Target is 4 hands/day, same as #1 -- the two
configs' near-identical scores (12157 vs 12037) are a consistency check,
not two different strategies.

**#3 -- fib-cap(5), never expand.** Same rule, cap raised to 5: hires up
through the 5th hand (fib(4)=5<=5), stopping before the 6th (fib(5)=8>5).
Target = 5 hands/day, cost 1+1+2+3+5 = 12/day. Never expand land.

**#4 -- flat(5), never expand.** Hire exactly 5 hands every day
(12/day total), never buy land. Slightly behind #3 (11760 vs 11942) --
within noise of each other, both representing the "5 hands on NW" point.

**#5 -- ramp(day0 to day10, 0 to 6 hands), never expand.** Target hand
count ramps linearly: target = round(6 * clamp((day-0)/(10-0), 0, 1)),
i.e. 0 on day 0, about 1 on day 2, about 3 on day 5, 6 on day 10 and every
day after. Never buy land. Notably worse than jumping straight to 4-5
hands on day 0 (#1-4) -- a slow ramp leaves labor on the table early game
for no payoff later.

**#6 -- flat(4) + land: utilization-gate(0.8).** The only land-buying
config in the top tier. Hire exactly 4 hands every day (as in #1). Every
turn, compute utilization = occupied_unlocked_tiles / total_unlocked_tiles
(a tile counts as occupied if it is a plant, weed, or structure -- anything
not None/LOCKED); the moment utilization >= 0.80, issue BUY_LAND (retried
every turn until it succeeds/affordable; no-ops harmlessly otherwise).
Buys NE first (then SW, then SE under the same rule) only once the current
land is nearly saturated by the already-established 4-hand crew. Confirmed
at 11087, essentially tied with pure flat(6) (#7, 11045) and meaningfully
better than any other land-buying strategy tested (next-best land
strategy: 5409).

**#7 -- flat(6), never expand.** Hire 6 hands/day (1+1+2+3+5+8=20/day),
never buy land. Behind #1-4: 6 units working 25 NW tiles is past the point
where extra hands add more than they cost in day-to-day hire fees -- see
crowding note below.

**#8 -- fib-cap(13), never expand.** Hires through the 7th hand
(fib(6)=13<=13, fib(7)=21>13 stops), i.e. 7 hands/day, 1+1+2+3+5+8+13=33
total. Never expand. Confirms the downward trend past 5-6 hands (10929,
below #1-7).

**#9/#10 -- flat(8), never expand.** Hire 8 hands/day
(1+1+2+3+5+8+13+21=54/day), never buy land. Worst of the "never expand"
family tested (10796/10657) -- 9 total units sharing 25 tiles is
past-optimal crowding: too many units chasing too few tiles, and the daily
hire fee for hands 7 and 8 (13, 21) is not earned back.

### The fib-cost breakeven point

Marginal hire ROI, read off the flat(n)/fib-cap(n) ladder (all
never-expand, 25 NW tiles, confirmed scores): flat(2)=9261, flat(3)=10319,
flat(4)=12157, flat(5)=11760, flat(6)=11045, flat(8)=10657/10796. The
curve peaks at 4 hands (5 units total) and is basically flat through 5,
then declines. In fib-cost terms: it is worth paying up through the 4th
hand's marginal cost of 3 (and arguably the 5th at 5), but hiring the 6th
hand onward (marginal cost 8, 13, 21) is a net loser on a single 25-tile
quadrant with this wheat loop -- there just is not enough tile-work left
for a 7th-9th unit to justify its daily fib fee once the first about 5
units are already covering the field.

## Other findings worth flagging

- Reserve-floor and "aggressive rush" archetypes underperform: both
  C_reserve_floor_conservative/C_reserve_floor_aggressive and
  C_aggressive_rush (flat(6) + buy land immediately) scored in the
  bottom third of screening (2251-2885) -- the land-purchase drag
  dominates any benefit from having cash reserved or hands ready.
- Money- and day-gated hiring lag flat/fib-cap hiring: money2k_2,
  day0_2, day5_2 (all capped at only 2 hands) land in the 9.3k-9.8k
  confirmed band -- reasonable, but simply under-hiring relative to the
  about-4-hand optimum, not a different failure mode.
- scaleland2 (2 hands per unlocked quadrant) never expands past NW in
  practice in these runs since land is never independently purchased by
  that policy alone when paired with land: never -- it is included to show
  that hand count scaled to land you do not have is just a flat-2 policy
  in disguise (9562, in line with the money/day-gated tier).
- Allocation mode matters more than several hiring-policy choices: the
  stripe-vs-quadrant screening gap (about 5400 vs about 4100, roughly 24%)
  is larger than the gap between, say, flat(3) and flat(6). Whatever
  hiring policy Dom picks, keep tile assignment as stripe (or something
  that behaves like it) rather than grouping units by quadrant.

## Recommendation

For this fixed wheat-loop task: hire up to 4 hands (5 units total) every
day from day 0, using stripe tile allocation, and do not buy land unless
you already have that many hands and 80 percent or more of your current
tiles are occupied (then buy the next quadrant once, re-checking the gate
before buying again). That is configs #1 and #6 above, which is the
overall best (#1, land-free) and the best land-inclusive strategy (#6),
respectively.

## Files

- `production.py` -- fixed wheat-loop unit behavior + tile allocation modes
- `policies.py` -- hire/land policy builders (all parametrized functions used above)
- `configs.py` -- all 69 base (hire, land) configurations
- `agent.py` -- wires a (hire_policy, land_policy, allocation) triple into an obs to action agent
- `sweep.py` -- two-phase screen/confirm runner (multiprocessing)
- `results/screen_results.json` -- all 69 phase-1 screening runs
- `results/allocation_screen_results.json` -- 12 allocation-mode probe runs
- `results/confirm_results.json` -- the 20 full-scale confirmed runs behind the leaderboard above
