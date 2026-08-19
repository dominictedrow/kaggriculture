# Tuning leader_clone into a strong sparring opponent

`leader_clone`'s job has changed. It doesn't need to be a byte-faithful
reconstruction of team カワシギ's source — it needs to be a **strong, stable
opponent to test our own agent designs against** in `harness.py`. Right now
it isn't: vs random ~30.8k mean, vs starter ~36.5k mean, and it loses
head-to-head to our own `ring.py` (which scores 83k/89k against the same
baselines). A sparring partner that folds to `random`-tier opponents at 3x
worse than our own agent doesn't teach us anything about how our designs
hold up under pressure. This file is the punch list for closing that gap,
ordered by expected impact per unit of effort, grounded in what the
debugging session already found.

## Measurement problem first

Individual-episode final money has a stdev of ~$15-20k on a ~$30-90k mean.
An n=6-8 batch comparison (what most of the tuning so far used) has a
standard error wide enough that two genuinely-different configs can look
like the change made things worse when it didn't, or vice versa — this is
what happened comparing the wheat-sell-surplus variants. Two fixes needed
before trusting any more A/B results:

1. **Pass a fixed `seed` in the `configuration` dict** (`kaggle_environments
   make("kaggriculture", configuration={"episodeSteps": 720, "seed": N})`)
   and reuse the same seed list across configs being compared, so both
   sides face identical weed-spawn RNG and shop-unlock draws. Paired
   comparison collapses most of the between-episode variance that's
   currently drowning the signal.
2. **n >= 20 per side** for any comparison whose conclusion will drive a
   kept-or-reverted decision. n=6-8 is fine for a smoke test ("did this
   crash"), not for a performance verdict.
3. Never run two `run_matches` calls concurrently in separate background
   shells — each spawns `os.cpu_count()` worker processes; two at once
   oversubscribes the machine and both get killed (happened once already).
   Run comparisons sequentially in one process, or explicitly cap
   `n_workers` so two calls fit.

## Idea 1 — shrink zone targets to what 12 hands can actually service

Diagnostic during the build: by day 20, leader_clone had **47 empty tiles**
out of ~60 targeted production tiles, with strawberry stuck at 13/20 and
wheat at 17/26 — the zones are sized for the real leader's execution
throughput, not this clone's. `ring.py` services 36 tiles (17 livestock +
19 melon) with 8 hands + farmer (9 units, 4.0 tiles/unit) and hits 83-89k.
leader_clone targets 60 tiles with 12 hands + farmer (13 units, 4.6
tiles/unit) — a similar ratio on paper, but clearly isn't converging to
full occupancy in practice, which means every unfilled tile is dead capital
(seed cost paid, tile claimed, nothing growing).

**Test:** cut `SUCCESSION_TILES` and `WHEAT_TILES` by ~25-30% (e.g. 20->14,
26->18) and re-measure tile occupancy at day 15/20/25 (not just final
money) to confirm zones actually fill up before chasing further tuning on
top of an under-serviced layout.

## Idea 2 — static hand->zone assignment instead of per-day proportional split

`role_split(n_hands)` recomputes the livestock:succession:wheat ratio fresh
every day from the *current* hand count, then `chunk_indices` re-partitions
each zone's tile list across whatever hands exist that day. Since hands are
re-hired daily anyway (RULES.md: they disappear at day-end), some
reshuffling is unavoidable — but the boundary math shifting on every
hire-count transition (the schedule changes count on ~20 of the 30 days)
means a hand's assigned tile *range* moves even when its *role* doesn't,
costing pathing time that should go to WATER/HARVEST/FEED.

**Test:** fix hand-slot -> zone assignment at the `TARGET_HANDS=12` ratio
permanently (slots 0-4 always livestock, 5-8 always succession, 9-11 always
wheat) rather than reproportioning for the current day's count. On
low-hire-count days, higher slots just don't exist yet (same effective
behavior early on) but the mapping never moves once a slot is active. This
was the original design instinct before switching to proportional — worth
an actual controlled test now that "some zones are idle early" turned out
not to be the dominant failure mode.

## Idea 3 — make each zone spatially contiguous

The cascading `_allocate_zones` interleaves each zone's tiles across NW,
NE, and SW (a "share of every quadrant" split) so that wheat has an early
foothold — which fixed the original wheat-locked-out bug. But it means a
single zone's tiles can be scattered across quadrant boundaries, and
`nearest_step`-based pathing (engine.py) is only efficient when a hand's
assigned tiles cluster together. Compare against giving each zone a single
contiguous block per quadrant phase (e.g. livestock's 14 tiles = NW's
hub-closest 14; once NE unlocks, succession's NE share is a contiguous
block, not scattered).

**Test:** measure average per-hand travel actions (MOVE-type actions
per HARVEST/WATER/FEED action) under the current interleaved layout vs a
contiguous-block layout, holding zone sizes fixed. If travel overhead drops
meaningfully, contiguity is worth the layout complexity; if not, leave the
simpler interleaved version.

## Idea 4 — let land purchases float instead of pinning to the observed calendar

Right now `LAND_BUY_TURNS` mirrors the real leader's exact turn-149/265/289
schedule (with a persistent affordability retry after that turn). But
leader_clone's economy doesn't track the real leader's cash curve — it was
still near-broke well past turn 149 during debugging. Pinning to their
calendar means land can arrive *later* than this clone's own economy could
support, which is pure lost production time.

**Test:** replace the turn-gated check with `engine.next_land_buy`-style
"buy as soon as affordable" (no minimum turn), same as `ring.py` already
does. This trades calendar fidelity for economic responsiveness — the
right trade now that the goal is strength, not a historical replica.

## Idea 5 — revisit wheat-surplus selling with a shed-pressure trigger instead of a fixed reserve

The fixed-reserve approach (hold N units, sell the rest) was tried at two
reserve sizes and both underperformed holding wheat entirely — either the
reserve was above actual production (nothing ever sold) or below the real
feed need (missed FEED actions, which is a severe penalty since two missed
feeds are unrecoverable). `engine.sell_orders` already has a
shed-capacity-pressure override (`n >= 90` bypasses the price floor) —
apply the same idea to wheat specifically: hold wheat by default, but sell
surplus once shed WHEAT crosses a high absolute threshold (e.g. 60-70) so
selling only triggers when there's genuinely more wheat than any
short-term feed swing could need, not based on a hand-tuned daily-reserve
guess.

## Idea 6 — reconsider the animal mix against ring.py's validated numbers

`ring.py`'s 11 COW / 6 SHEEP was independently tuned and validated (83-89k
vs baselines) in `strategies_v2/compare.json`. leader_clone's 10 COW / 4
SHEEP came from the replay's tile-count curve, but that number was
measured in a *different* economy (the real leader's), not tested here.
Once idea 1 fixes zone occupancy, try swapping in ring's animal ratio (or a
small sweep around it) as a cheap independent check on whether observed
imitation is actually better than something we've already validated
ourselves.

## Suggested order

1 and 4 are the highest-confidence, lowest-effort fixes (both are directly
implicated by data already gathered during the build, not speculative) —
do those first and re-measure with the seeded/n>=20 methodology above
before touching 2, 3, 5, or 6, since fixing occupancy and land timing may
close most of the gap on their own and change what's worth tuning next.

## Outcome (all 6 ideas tried)

Every idea above was implemented and validated with `harness.compare_paired`
(seeded, n=20-40). All six measured worse or statistically indistinguishable
from `leader_clone`'s original values and were reverted -- see inline
comments at each constant in `leader_clone.py` for the per-idea numbers.
Root cause: `HIRE_SCHEDULE`'s 12-hand peak costs $376/day at fibonacci
per-hire pricing, and this clone's economy can't sustain that (money sits
near $0 most days in a seeded trace) -- every idea here either competed
with `HIRE` for that scarce cash or failed to address the shortfall. That
schedule was copied as an *output number* (how many hands the real leader
ended up with each day), not as a *decision rule* -- and a number that
worked for their unrecovered economy doesn't automatically work for ours.
This motivates the plan below: stop guessing at reconstructed aggregates
and pull the actual per-turn decision rules straight out of replay data,
for the leader and the rest of the top 10.

## Next: extract literal playbooks from replay actions, not aggregate stats

Confirmed this session: `kaggle_replays/replays/*.json` is not a stats
dump -- each of the 720 steps records the full `(observation, action)` pair
for both players, so the exact action taken at every turn (which tile, which
op, which hand) is already sitting on disk. `leader_clone.py`'s "inferred"
section (zone sizes, hand-to-zone split, sell policy) only exists because
the earlier analysis (`analyze_leader.py`) worked off aggregate tile-count
summaries, not the raw per-step actions it could have used. Also already in
place: `kaggle_replays/episode_lists/` has 10 files (one per top-10
submission ID), and `kaggle_replays/replays/` already holds ~1000
downloaded games spanning all 10 -- the data for this is local right now,
nothing new to fetch for the extraction step itself.

1. **Identify each submission's player slot per episode.** Each replay's
   `info["TeamNames"]` gives both teams' names but not which one owns a
   given `episode_lists/<submission_id>.json`. Fix: for each submission ID,
   take the intersection of `TeamNames` across every one of its downloaded
   episodes -- the name common to all of them (opponents vary, the
   submission owner doesn't) is that submission's team, and its index in
   `TeamNames` is its player slot in that episode. Generalizes
   `analyze_leader.py`'s hardcoded `LEADER_NAME` check to all 10.

2. **Extract per-hand tile trajectories.** For each submission, walk every
   step of every one of its episodes and record, per hand-slot index,
   `(position, tile-state-before, action)` over time. Clustering a slot's
   positions directly recovers its *actual* assigned zone and tile
   footprint -- exact, not a tile-count-curve guess. This replaces
   `leader_clone.py`'s inferred `SUCCESSION_TILES`/`WHEAT_TILES`/zone-split
   entirely with observed ground truth.

3. **Extract the market-order decision rules, not just their outputs.**
   For every `BUY_SEED`/`BUY_ANIMAL`/`HIRE`/`BUY_LAND`/`SELL` action,
   correlate it against the paired observation (day, hour, money, shed
   levels, empty-tile counts, prices) to fit the actual triggering
   condition -- e.g. regress `SELL WHEAT` events against shed level and
   price at time of sale to recover their real threshold, instead of the
   blind 20-70 sweep idea 5 already tried and failed to land. Also settles
   the affordability ambiguity `HIRE_SCHEDULE` left open: if the same
   agent's issued `HIRE` count is ever capped by that day's actual money
   (visible in `farms[i]["money"]` the turn before), that day's number was
   an outcome, not a target -- know which is which before copying it.

4. **Run the same extraction across all 10 submissions and diff the
   results.** Elements that converge across multiple independently-built
   top agents (e.g. several landing on a similar zone tiles/hand ratio, or
   a similar sell-price floor) are more likely genuinely load-bearing than
   idiosyncratic to one team, and are worth prioritizing. Elements only the
   #1 team does are candidates but not assumptions.

5. **Re-implement each finding as a state-dependent rule, not a copied
   number, and validate before merging.** The mistake this pass just spent
   effort discovering: `HIRE_SCHEDULE = {day: count}` is a fixed schedule
   that assumes an economy we don't have. A rule extracted from step 3 --
   e.g. "hire until the next hire would leave money below the wheat/seed
   budget for the day" -- is a *function of our own state*, so it adapts to
   our own cash trajectory instead of assuming theirs. Any such rule still
   goes through `harness.compare_paired` (seeded, n>=20) against the current
   `leader_clone`/`ring.py` baselines before it's kept -- same discipline
   that reverted all 6 ideas above, now applied to extraction results
   instead of guesses.
