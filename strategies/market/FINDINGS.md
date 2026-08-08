# Market Tactics (Selling/Buying) -- Findings

Domain under test: sell batching/timing and buy-arbitrage tactics, isolated
from production choices. **Absolute money numbers here are much lower than
the crops/livestock domains on purpose** -- production is deliberately held
small and fixed so every difference in outcome is attributable to the
market-tactic layer, not to what's being grown. Treat these findings as
*relative* tactics to graft onto a stronger production plan (e.g. the crops
domain's melon-mono), not as a standalone strategy.

## Fixed production baseline (identical in every config below)

A single farmer, no hired hands, no fertilizer, no animals, walks a fixed
12-tile snake path in the NW quadrant centered on the shed-adjacent spawn
tile (4,4): 6 WHEAT tiles then 6 CARROT tiles, each planted, watered daily,
harvested at `max_yield_day` (age 4 for wheat, age 3 for carrot -- peak
unfertilized yield), then replanted. Seed buying is automatic upkeep. SELL /
BUY_PRODUCT decisions are the only thing that varies between configs (see
`policy.py::build_market_orders`).

Resource price-curve context (from RULES.md): **wheat** (base $25) panics on
scarcity but *absorbs gluts cheaply* (`above_target=0.20`, log) -- dumping is
close to free. **Carrot** (base $35) is the mirror image: mild scarcity
reaction but *craters hard on oversupply* (`above_target=0.70`, sqrt;
`P(I0+2T) = $1`) -- naive dumping risks crashing your own price.

## Method

- Screen: 65 configs (wheat-axis sweep with carrot fixed at dump, carrot-axis
  sweep with wheat fixed at dump, cross-combos, arbitrage add-ons), n=6
  episodes/opponent x episode_steps unspecified-short. See `results_screen.csv`
  and `sweep_log.txt` (lines 1-337).
- Confirm: top 20 by screening score, full scale -- n=30 episodes/opponent x
  episode_steps=720. **19 of 20 completed** before the run was interrupted;
  the 20th (`combo_capped15_x_dayspread4`, screened ~3834) was not confirmed
  and is excluded below. See `sweep_log.txt` (tail, "Confirming top 20...").
  Ranking metric: `combined = 0.5 * mean(vs random) + 0.5 * mean(vs starter)`.
- Pure dump-both baseline (`wheat_dump`+`carrot_dump`, screening scale only):
  combined ~4181. The best confirmed tactic below beats this by ~43%.

## Confirmed leaderboard (n=30/opponent, episode_steps=720)

| # | Config | WHEAT rule | CARROT rule | Combined |
|---|---|---|---|---|
| 1 | wheat_pricegate_20 | price_gate(min=$20) | dump | **5971** |
| 2 | carrot_threshold_10 | dump | threshold(>=10 units) | 5965 |
| 3 | combo_dump_x_threshprice_10_25 | dump | threshold(10) AND price_gate($25) | 5958 |
| 4 | carrot_pricegate_30 | dump | price_gate(min=$30) | 5937 |
| 4 | carrot_shopscaled_3_1 | dump | cap = 3 + 1x(unlocked shops) | 5937 |
| 4 | combo_dump_x_threshold10 | dump | threshold(>=10 units) | 5937 |
| 7 | carrot_threshprice_10_25 | dump | threshold(10) AND price_gate($25) | 5932 |
| 8 | wheat_capped_30 | cap 30 units/turn | dump | 5930 |
| 9 | wheat_capped_5 | cap 5 units/turn | dump | 5928 |
| 10 | carrot_gatehours_4 | dump | sell all only every 4th hour | 5923 |

Full 19-entry confirmed set is in `sweep_log.txt`. Note the near-tie across
entries #1-10 (5923-5971, a 0.8% spread) -- once wheat is left on
dump-or-mild-price-gate, the *carrot* tactic barely matters among
threshold/price-gate/shop-scaled variants; what matters is picking any of
them over naive dump.

## Top result, exact reimplementable rule (#1, combined $5,971)

**Dump wheat immediately; gate wheat sales at a $20 price floor is
marginally better than unconditional dump; carrot: sell immediately
(dump) every turn.**

Concretely, every turn:
- `if shed["WHEAT"] > 0 and prices["WHEAT"] >= 20: SELL WHEAT <shed_qty>`
  (else hold).
- `if shed["CARROT"] > 0: SELL CARROT <shed_qty>` (unconditional dump).

**Why it wins, and why the margin over plain dump-both is thin for wheat
specifically:** wheat's price curve absorbs oversupply cheaply (log-shaped,
`above_target=0.20`), so gating at $20 (below its $25 base) almost never
actually blocks a sale -- it only helps in the rare case price has dipped
below $20 from a prior glut, letting it recover before you sell into it. The
real lever is on the **carrot** side.

## Runner-up mechanism: carrot needs gating, wheat doesn't (#2-10)

Every top-10 entry either dumps carrot (when wheat is the one being gated,
e.g. #1) or gates/batches carrot specifically (#2-10, all variants of
threshold / price-gate / shop-scaled / hour-gated selling). This matches
carrot's price curve: `above_target=0.70` with a `sqrt` shape means
oversupply crashes it hard (`P(I0+2T) = $1` -- the literal floor). At this
farm's production volume (6 carrot tiles) the crash risk is small, which is
why the gap between gated-carrot and dump-both-naive is only ~43% rather
than catastrophic -- but it compounds with scale: a bigger farm selling more
carrot per turn would see the gap widen sharply, since dumping a bigger
batch drives the price down further per the "concurrent, one-unit-at-a-time"
processing rule (RULES.md, Market Mechanics).

Concrete alternative rules that tied for #4 (5937, statistically
indistinguishable from each other given n=30 noise):
- **price_gate($30)**: `if shed["CARROT"] >= 1 and prices["CARROT"] >= 30: SELL CARROT <shed_qty>`.
- **shop_scaled_cap(base=3, bonus=1)**: `cap = 3 + 1 * num_unlocked_shop_instances; SELL CARROT min(shed_qty, cap)` every turn (sells more as town demand grows).
- **threshold(10)**: `if shed["CARROT"] >= 10: SELL CARROT <shed_qty>` (batch up, then dump the whole batch).

## What didn't help

- **`threshold20` on wheat** (gate wheat sales until 20+ units are banked)
  scored ~5300-5384 across every carrot pairing tested -- 550-650 points
  *worse* than the same carrot tactic paired with wheat-dump. Holding wheat
  back has a real opportunity cost (delayed cash -> delayed reinvestment)
  and wheat's glut-absorbing price curve means there's little price-crash
  risk being protected against in the first place.
- **`day_spread`** (sell only 1/k of the batch at hour 0 each day) scored
  noticeably lower than threshold/price-gate alternatives in screening
  (`carrot_dayspread_7`: 3659 vs `carrot_threshold_10`: ~4188 at screening
  scale) -- spreading a small batch this thin just delays cash for no
  proportionate price benefit at this production volume.
- **`hoard`** (never sell carrot) was the single worst carrot tactic in
  screening (3317) -- obviously, money in the shed isn't money in the bank.
- **Wheat/fertilizer buy-arbitrage** (`arb_wheat_only`, `arb_fert_only`,
  `arb_both`, `arb_wheat_aggressive`) all screened within noise of the
  no-arbitrage default (4161-4179 vs default's price_gate25 baseline) --
  buying low and reselling high on a resource you're not otherwise using
  isn't worth the market-order slots at this farm's cash scale.
