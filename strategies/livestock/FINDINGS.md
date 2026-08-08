# Livestock (Goose/Cow/Sheep) -- Findings

Domain under test: which animal(s) to raise and in what mix, coop/pasture
build timing, feed/care discipline, the CARE bonus-banking mechanic, and
`COLLECT_FERTILIZER` discipline. Agent code is config-driven
(`agent_lib.py::make_agent`); every entry below is the same code with
different `animal_plan` / `feed_mode` / `care_mode` / `num_hands` / etc.

Key mechanic exploited by the whole domain (see RULES.md's Animal Care
section): scheduled base production (+1 unit) fires on interval whether or
not the animal was fed *that specific day* -- only the banked CARE bonus
requires same-day feed on the production day itself. Feeding is only
mandatory often enough to avoid 2 consecutive unfed days (unrecoverable
escape).

## Method

Two-phase sweep:
- Screen 1 (baseline): single-animal-type configs at various counts, see
  `results/screen1_baseline.json`.
- Screen 2 (variants): mixes (cow+sheep, goose+cow+sheep), hiring, feed/care
  modes, staggered buying, wheat-buffer slack, start-day delay, see
  `results/screen2_variants.json`.
- Confirm: top screening survivors, full scale -- n=30 episodes per opponent
  x (random, starter) x episode_steps=720 (60 episodes each). See
  `results/confirm_final.json`. Ranking metric throughout:
  `combined = 0.5 * mean(vs random) + 0.5 * mean(vs starter)`.

## Confirmed leaderboard (n=30/opponent, episode_steps=720)

Re-ranked here by combined mean (the raw JSON is in insertion, not ranked,
order):

| # | Config | Animal plan | Hands | Combined | vs random (mean) | vs starter (mean) |
|---|---|---|---|---|---|---|
| 1 | mix_c4s2_hands2 | 4 COW + 2 SHEEP | 2 | **50316** | 50652 | 49980 |
| 2 | mix_c3s3_hands1 | 3 COW + 3 SHEEP | 1 | 49644 | 51204 | 48085 |
| 3 | mix_c4s2_hands1 | 4 COW + 2 SHEEP | 1 | 49176 | 50758 | 47593 |
| 4 | mix_c3s3_hands2 | 3 COW + 3 SHEEP | 2 | 48648 | 49429 | 47868 |
| 5 | cow6_hands1 | 6 COW | 1 | 45819 | 45793 | 45846 |
| 6 | cow6_hands2 | 6 COW | 2 | 42662 | 42053 | 43270 |
| 7 | mix_c4s2_stagger1 | 4 COW + 2 SHEEP | 0 | 43838 | 43389 | 44286 |
| 8 | mix_c3s3_stagger1 | 3 COW + 3 SHEEP | 0 | 42493 | 42401 | 42585 |
| 9 | mix_c4s2_wheatslack3 | 4 COW + 2 SHEEP | 0 | 41906 | 41854 | 41958 |
| 10 | mix_c4s2_start2 | 4 COW + 2 SHEEP | 0 | 41786 | 41220 | 42352 |

All entries use `feed_mode="daily"`, `care_mode="always"`, `collect_fert=True`
unless noted; full 17-entry confirmed set is in `results/confirm_final.json`.

## Top result, exact reimplementable rule (#1, combined $50,316)

**4 cows + 2 sheep on pastures (no goose/coop), 2 hired hands, feed and care
every animal every day without fail, sell every non-wheat item the instant
it's in the shed.**

- Roster: buy 4 COW ($400 each) + 2 SHEEP ($500 each) as early as money
  allows (no `start_day` delay, no `max_buy_per_day` cap -- buy as many as
  affordable each day until the full roster of 6 is reached).
- Structures: both COW and SHEEP use `PASTURE` (goose is the only one that
  needs a `COOP`) -- `BUILD_PASTURE` on each of the 6 assigned tiles before
  placing an animal there.
- Assignment: 6 animal-tiles split into 3 contiguous chunks (farmer + 2
  hands), each unit only ever walks its own chunk.
- Every turn, for each unit standing on one of its assigned tiles:
  1. Empty pasture + animal in hand -> `PLACE <animal>`.
  2. Occupied pasture, animal not fed today, wheat in hand -> `FEED`.
  3. Occupied pasture, fed today, `yield_units > 0` -> `HARVEST`.
  4. Occupied pasture, nothing to harvest, `fertilizer_available` -> `COLLECT_FERTILIZER`.
  5. Occupied pasture, fed today but not cared today -> `CARE` (banks
     `pending_care_bonus += 1`, paid out in full on the animal's next
     scheduled production tick).
  6. Otherwise step toward the nearest assigned tile that needs one of the above.
- Shed-adjacent pickup: on reaching one of the 4 center tiles, pick up
  enough WHEAT to cover the unit's entire chunk in one visit (so it never
  has to shuttle back mid-route), and pick up any needed animals waiting in
  the shed.
- Wheat purchasing: every turn, `BUY_PRODUCT WHEAT <deficit>` to keep total
  held+shed wheat at exactly `total_animal_count` (6) -- no slack buffer.
- Selling: every turn, `SELL <item> <shed_qty>` for every shed item except
  WHEAT (dump-immediate on milk, wool, and fertilizer alike).
- Hiring: 2 `HIRE` orders every day at hour 0 (fib-cost, resets daily).

**Why it wins:** cow (milk, $160 base, 2-day interval) and sheep (wool, $200
base, 3-day interval) both out-earn goose ($50 egg base) per action spent,
and CARE's banked bonus (+1 per fed-and-cared day, paid out whole on the next
scheduled tick) compounds nicely on cow's every-2-days cadence without
costing an extra action beyond what daily upkeep already requires. 2 hands
(#1, #4) beat 1 hand (#2, #3) for the same animal mix once the roster is
large enough (6 animals) that a single unit's daily circuit becomes the
bottleneck -- but going further to `cow6_hands2` (#6, all-cow, no sheep) is
worse than the mixed roster despite the same 6-animal count and 2 hands,
because a 6-cow roster is far higher variance (stdev ~17,000 vs ~6,700 for
the 4:2 mix) -- see raw JSON `min` values: cow-only configs occasionally
crash to $15-16k when RNG-driven weed spawns or wheat-price spikes hit a
homogeneous herd, while the cow+sheep mix's staggered production intervals
smooth that out.

## What didn't help

- **`stagger1`** (max 1 new animal bought per day instead of buying the full
  affordable roster immediately) cost roughly $6-7k combined vs the
  unstaggered equivalent (#7 vs #1) -- delaying roster completion delays
  every animal's first-yield clock, and the delay is never recovered in a
  30-day season.
- **`wheatslack=3`** (buying 3 extra wheat units/day beyond exact need, as a
  feed buffer) underperformed the zero-slack default by ~$8,400 (#9 vs #1)
  -- the extra wheat purchases at market price are pure cost with no upside
  once feed logistics are already handled by the single-visit pickup rule.
- **`start_day=2`** (delay the whole operation 2 days to bank starting cash
  first) cost ~$8,500 vs starting immediately (#10 vs #1) -- animals are
  expensive ($400-500) and slow to pay off (first yield at day 6-8), so
  every day of delay is a day of lost production window in a fixed 30-day
  season.
- **Goose in the mix** (`mix_g2c2s2`, 2 goose + 2 cow + 2 sheep) scored
  lowest of any mix tested in screening (~$33k combined) -- goose's $50 egg
  base price is far behind cow/sheep, so tiles spent on goose are tiles not
  spent on the better-paying animals.
