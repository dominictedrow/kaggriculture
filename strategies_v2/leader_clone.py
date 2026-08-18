"""LEADER_CLONE -- reconstruction of the #1 leaderboard agent (team "카ワシギ",
submission 55425101, 3238.2 score, 89.3% win rate over 149 replay-analyzed
games), built from replay analysis, not their source (which we don't have).

What's an exact match (measured with zero variance across all 149 replays,
so treated as ground truth rather than inferred):
  - Opening burst: 5x HIRE, BUY_ANIMAL COW 2, BUY_ANIMAL SHEEP 2, BUY_SEED
    MELON, all in one order list at day 0 hour 1 (turn 1). Turn 0 is
    farmer-positioning only, no market orders.
  - HIRE_SCHEDULE: the exact hire count issued every day, identical across
    all 5 spot-checked full per-day traces AND matching the aggregate
    medians across all 149 games.
  - LAND_BUY_TURNS: BUY_LAND at turn 149 (day 6) and turn 265 (day 11) in
    100% of games (zero variance); a third BUY_LAND at turn 289 (day 12) in
    only 42/149 games -- conditional on having $4000 spare, so implemented
    as an affordability check rather than unconditional.

What's inferred from tile-count curves (median tile counts by day), since
the exact zone-assignment/pathing algorithm isn't recoverable from replay
data alone:
  - Livestock converges to 10 COW / 4 SHEEP by day 15 and holds there.
  - Melon is front-loaded to ~20 tiles by day 10, then deliberately stops
    being replanted (last plant ~day 9) so the 10-day-cycle tiles clear out
    and get replaced by STRAWBERRY on the same footprint -- melon tile count
    drops from 20 (day10) to 0 (day20) while strawberry rises from ~11
    (day10) to ~34 (day15-20) on what is plausibly the same physical zone.
  - A separate, always-growing WHEAT zone reaches ~26 tiles by day 25 (feed
    supply + cash crop) -- wheat surplus beyond a feed reserve gets sold,
    not just held (unlike our other strategies_v2 scripts, which hold ALL
    wheat; this agent sells ~1200 wheat/game, so it clearly doesn't).
  - Hand-to-zone assignment is split proportionally across the three zones
    (5 : 4 : 3, matching the 12-hand peak) rather than a fixed order,
    because melon/wheat tiles are already growing in day 1 -- if hands were
    assigned livestock-first then melon/wheat, those zones would sit idle
    until the hire count exceeded the livestock group's size, which isn't
    what the data shows.
  - Endgame weed buildup (0 -> ~17 tiles by day 29) and crop wind-down are
    NOT special-cased -- they fall out for free from the HIRE_SCHEDULE
    taper (12 -> 8 hands) and the last_buy_day cutoffs already in engine.py.

Losses in the replay sample (16/149, 10.7%) were not caused by execution
differences -- every internal metric (hires, digs, land timing, melon/cow/
sheep counts) was statistically identical between wins and losses. The
actual driver was WOOL and MILK sell prices collapsing (-57% / -52% vs.
win-game averages) at unchanged sell volumes -- a shared-market glut, the
exact risk strategy.md already flags for wool/milk. This agent has no
opponent-awareness at all to defend against that -- see CLAUDE.md's watcher.

1st.md tuning pass (all 6 ideas tried, all reverted -- see inline comments
at each constant for the per-idea numbers): every idea individually tested
worse or statistically indistinguishable from the values below, in seeded
n=20-40 paired comparisons (harness.compare_paired, same weed-spawn/
shop-unlock RNG on both sides of each test). The common thread: this
economy is chronically cash-starved (shed money sits near $0 most days in
a seeded trace) because HIRE_SCHEDULE's peak (12 hands/day) costs $376/day
at the fibonacci per-hire rate, and every tested change either competed
with HIRE for that scarce cash (idea 4: land), cut revenue capacity without
fixing the shortfall (idea 1: zone size), reintroduced a feed-starvation
failure mode against the schedule's non-monotonic hire counts (idea 2:
fixed hand slots), or showed no consistent effect (idea 5: wheat
sell-threshold; idea 6: ring's animal ratio, which made cash starvation
worse via extra upfront/feed cost). Idea 3 (zone contiguity) was evaluated
but not implemented -- the existing zone layout already gives each zone one
contiguous block per quadrant, and further consolidation risks the same
starvation class of bug. HIRE_SCHEDULE's fibonacci cost at a 12-hand peak
is the more likely root cause of the underperformance 1st.md set out to
fix, but redesigning it is out of scope for this pass (see harness.py for
the seeded/paired A/B infrastructure this pass added, which stays useful
for testing that or any future change).

1st.md "Next" extraction pass (kaggle_replays/extract_playbooks.py +
compare_playbooks.py): replaced the tile-count-curve guessing above with
literal per-turn replay actions across all 10 top-10 submissions (1066
episode-files), fixing a real bug found along the way -- kaggle_environments
replay steps pair steps[t].observation with the state AFTER steps[t].action
was applied, not before, so every earlier "*_before" analysis (this file's
included) was silently reading actions against their own outcome. Findings,
all in kaggle_replays/PLAYBOOK_FINDINGS.md:
  - Ground truth (not guessed) zone footprint: the real leader holds 34
    STRAWBERRY tiles at day15-20 (not this file's 20), and all 4
    independent top-10 designs (after collapsing a 7-way duplicate/forked-
    notebook cluster to one data point) converge on ~70-75 production tiles
    at peak season -- day 29 (used by the original inferred analysis above)
    is season wind-down, not the zone's real size.
  - Every one of the 10 sells WHEAT surplus routinely, none hold it all.
  - Every one of the 10 funds its NE land purchase with a same-turn SELL
    queued before BUY_LAND (100% underfunded at turn-start otherwise).
Implementing these directly (SUCCESSION_TILES 20->34; a WHEAT reserve+floor
sell rule; sells-before-buys ordering) was tried and REVERTED -- both
individually and combined it measured $8-14k WORSE (seeded n=20 paired vs
random/starter, see inline comments at each constant). Two different
plausible mechanisms, neither confirmed: the bigger zone spends into the
same HIRE-starved cash pool as every prior zone-size idea; the reorder can
let sells eat into `maxMarketOrdersPerTurn`'s 10-order cap ahead of HIRE on
high-hire days. The ground-truth *targets* are real and this agent
genuinely under-produces relative to the actual top 10 -- but bolting them
onto the current HIRE_SCHEDULE-driven cash-starved economy doesn't help;
per the paragraph above, that root cause needs fixing first.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from engine import (
    LAND_COST, LAST_SEASON_DAY, QUADRANT_TILES, chunk_indices, crop_action,
    last_buy_day, livestock_action, sell_orders,
)

# ---- exact, zero-variance calendar (see module docstring) -----------------

HIRE_SCHEDULE = {
    0: 5, 1: 0, 2: 4, 3: 5, 4: 5, 5: 4, 6: 4, 7: 8, 8: 11, 9: 12, 10: 11,
    11: 12, 12: 10, 13: 11, 14: 8, 15: 12, 16: 9, 17: 12, 18: 12, 19: 12,
    20: 12, 21: 12, 22: 12, 23: 12, 24: 11, 25: 11, 26: 11, 27: 11, 28: 10,
    29: 8,
}
LAND_BUY_TURNS = {"NE": 149, "SW": 265, "SE": 289}
LAND_ORDER = ["NE", "SW", "SE"]
# idea 4 (1st.md) was tried and reverted: floating land purchases on
# affordability alone (no minimum turn) measured WORSE in seeded n=20 paired
# testing (-$10k mean vs the calendar gate, both alone and combined with
# idea 1) -- this economy is chronically cash-starved (money sits near $0
# most days; see idea-1 note below), and HIRE's fibonacci cost means
# whatever cash floating land grabs early is cash HIRE can't use, which
# costs more hands than the earlier land unlock gains back. The calendar
# gate accidentally protects HIRE's cash share early game; kept as-is.

# ---- inferred zone sizing (see module docstring) ---------------------------

ANIMAL_MIX = {"COW": 10, "SHEEP": 4}
# idea 6 (1st.md) was tried and reverted: swapping in ring.py's validated
# 11 COW / 6 SHEEP measured clearly WORSE here (n=20 paired, t=-2.3 vs
# random, t=-4.2 vs starter) -- ring's ratio is tuned for ring's own leaner
# 9-unit footprint; the bigger herd's extra ~$1400 upfront and +3/day feed
# demand compounds this agent's already-confirmed cash starvation (see idea
# 4's note above) rather than paying off. Kept at the replay-inferred 10/4.
ANIMAL_COST = {"COW": 400, "SHEEP": 500}
SUCCESSION_TILES = 20        # melon -> strawberry shared footprint
# 1st.md "Next" extraction pass (kaggle_replays/extract_playbooks.py,
# ground-truth tile occupancy from replay actions, not aggregate-curve
# guessing) found the real leader holds 34 STRAWBERRY tiles at day15-20 (not
# 20), and total production-tile count across ALL 10 top-10 submissions
# converges to ~70-75 tiles at peak season regardless of hand count (4
# independent designs after collapsing a 7-way duplicate/forked-notebook
# cluster to one data point -- see kaggle_replays/PLAYBOOK_FINDINGS.md).
# Raising SUCCESSION_TILES to 34 to match was TRIED and REVERTED: seeded
# n=20 paired vs random/starter measured -$14.2k / -$10.5k mean (both several
# stdev outside noise). Consistent with idea1/idea6's already-confirmed cash
# starvation (see module Outcome section) -- more seed cost from a bigger
# zone competes with HIRE for the same scarce cash, same failure mode as
# every previous zone/herd-size change, just in the opposite direction this
# time. The ground-truth *target* is real (this agent under-produces
# relative to the actual top 10), but hitting it needs the cash-starvation
# root cause fixed first (see Outcome), not a bigger zone bolted onto the
# same broke economy. Kept at 20 pending that.
WHEAT_TILES = 26             # ground truth: real leader's WHEAT tile count
                              # at day20/25 is 26/30 -- already close, unchanged
MELON_STOP_DAY = 9           # last melon PLANT/BUY_SEED day; 10-day cycle
                              # clears by ~day19-20, matching the data

CROP_MAX_YIELD_DAY = {"MELON": 10, "WHEAT": 4, "STRAWBERRY": 16}
LAST_BUY_DAY = {
    "COW": last_buy_day("COW"),
    "SHEEP": last_buy_day("SHEEP"),
    "MELON": MELON_STOP_DAY,
    "WHEAT": last_buy_day("WHEAT"),
    "STRAWBERRY": LAST_SEASON_DAY - 10,  # first_yield_day = 10 (RULES.md)
}
SELL_MIN_PRICE_FRAC = 0.4
BASE_PRICE = {"MELON": 250, "STRAWBERRY": 120, "WOOL": 200, "MILK": 160, "CARROT": 35}
TARGET_QUADRANTS = 3  # NW + NE + SW unconditional; SE conditional (see LAND_BUY_TURNS)

HUB = (4.5, 4.5)


def _livestock_types():
    seq = []
    for animal, count in ANIMAL_MIX.items():
        seq += [animal] * count
    return seq


LIVESTOCK_TYPES = _livestock_types()


def _hub_sort(tiles):
    return sorted(tiles, key=lambda p: (abs(p[0] - HUB[0]) + abs(p[1] - HUB[1]), p[1], p[0]))


def _allocate_zones(quadrant_tile_lists, targets):
    """Give every zone a foothold in the earliest-available quadrant instead
    of letting one zone exhaust NW before the next zone gets anything --
    day-1 replay data shows livestock, melon, AND wheat tiles all already
    growing together in NW before any land is bought, not sequentially.

    idea 3 (1st.md) evaluated, not applied: this already produces one
    contiguous run per zone per quadrant (verified -- a zone's NW tiles are
    one unbroken slice, not interleaved tile-by-tile with the other zones),
    so the "scattering" idea 3 flags is only the split across quadrant
    boundaries, which is inherent to the early-foothold property above.
    Collapsing each zone to a single quadrant-only block would reintroduce
    the wheat/succession lockout this function was written to fix (ideas 1
    and 2 both independently confirmed how costly that starvation failure
    mode is against this agent's non-monotonic HIRE_SCHEDULE). MOVE actions
    are ~49% of all hand actions (measured), but that's mostly ordinary
    in-zone travel, not zone-scatter specifically -- not chased further
    given the regression risk and the smaller expected payoff vs. ideas
    5/6."""
    remaining = dict(targets)
    result = {z: [] for z in targets}
    for qtiles in quadrant_tile_lists:
        avail = list(qtiles)
        idx = 0
        while idx < len(avail) and sum(remaining.values()) > 0:
            total_remaining = sum(remaining.values())
            n_left_in_quadrant = len(avail) - idx
            for z, need in list(remaining.items()):
                if need <= 0:
                    continue
                share = need if total_remaining <= n_left_in_quadrant else max(
                    1, round(n_left_in_quadrant * need / total_remaining)
                )
                share = min(share, need, len(avail) - idx)
                if share <= 0:
                    continue
                result[z].extend(avail[idx:idx + share])
                remaining[z] -= share
                idx += share
    return result


_ZONES = _allocate_zones(
    [_hub_sort(QUADRANT_TILES["NW"]), _hub_sort(QUADRANT_TILES["NE"]), _hub_sort(QUADRANT_TILES["SW"])],
    {"livestock": len(LIVESTOCK_TYPES), "succession": SUCCESSION_TILES, "wheat": WHEAT_TILES},
)
LIVESTOCK_POSITIONS = _ZONES["livestock"]
SUCCESSION_POSITIONS = _ZONES["succession"]
WHEAT_POSITIONS = _ZONES["wheat"]


TARGET_HANDS = 12  # peak of HIRE_SCHEDULE -- role_split() scales proportionally


def role_split(n_hands):
    """Proportionally split n_hands across livestock:succession:wheat at a
    5:4:3 ratio (the 12-hand peak's exact composition) -- scales down for
    the early-game ramp instead of filling one zone before the next, which
    is what the day-1 melon/wheat tile counts already show is happening.

    idea 2 (1st.md) was tried and reverted: fixed hand-slot -> zone
    assignment (livestock always slots 0-4, succession 5-8, wheat 9-11)
    measured worse (higher variance, some $0-money runs) because
    HIRE_SCHEDULE isn't monotonically increasing -- it dips well below 10
    on 11 of 30 days (day 14: 8, day 16: 9, day 29: 8, plus the early ramp),
    and a fixed 5+4 priority means wheat (feed supply) gets ZERO hands on
    every one of those days. Proportional always gives wheat at least one
    hand once there's more than a couple hands total, so it doesn't have
    this starvation failure mode; the boundary-reshuffling cost idea 2 was
    trying to fix is real but smaller than the feed-starvation risk of the
    fix."""
    if n_hands <= 0:
        return 0, 0, 0
    live = round(n_hands * 5 / TARGET_HANDS)
    succ = round(n_hands * 4 / TARGET_HANDS)
    live = min(live, n_hands)
    succ = min(succ, n_hands - live)
    wheat = n_hands - live - succ
    return live, succ, wheat


def agent(obs):
    player = obs["player"]
    me = obs["farms"][player]
    private = obs["private"]
    day = obs["day"]
    hour = obs["hour"]
    turn = day * 24 + hour
    tiles = me["tiles"]
    shed = private.get("shed", {})
    seeds = private.get("seeds", {})
    money = me["money"]
    inventories = private.get("inventories", [{}])
    prices = obs.get("market", {}).get("prices", {})

    buy_orders = []
    # idea 5 (1st.md) guessed thresholds (fixed reserves, then a 40-65
    # absolute-shed trigger) and both failed to land -- see module docstring.
    # The 1st.md "Next" extraction pass replaced guessing with ground truth
    # (every one of the 10 top-10 submissions sells WHEAT surplus routinely,
    # none hold it all -- kaggle_replays/PLAYBOOK_FINDINGS.md) and tried a
    # small-reserve ($20-21 floor, ~14-unit reserve) sell rule built from
    # that data. Also REVERTED: seeded n=20 paired vs random/starter measured
    # -$8.2k / -$8.4k mean, both clearly outside noise. Most likely cause:
    # selling wheat down to a fixed reserve every turn it's above threshold,
    # then hour1 buying it back on a deficit, round-trips through the
    # market's own price impact (sell depresses price, buyback pays a worse
    # one) for wheat this agent produces itself -- a cost the real leader's
    # actual (much lower-variance, event-triggered) sell logic apparently
    # avoids but a flat reserve-threshold rule doesn't reproduce. Holding all
    # wheat for feed -- the same convention ring.py / solid.py / checker.py
    # already use -- stays the simpler, equally-good option pending a rule
    # that captures the real trigger, not just the real threshold.
    sells = sell_orders(shed, prices, BASE_PRICE, SELL_MIN_PRICE_FRAC)

    if hour == 0:
        for _ in range(HIRE_SCHEDULE.get(day, 0)):
            buy_orders.append(["HIRE"])

    if hour == 1:
        wheat_needed = len(LIVESTOCK_TYPES)
        wheat_have = shed.get("WHEAT", 0)
        for inv in inventories:
            wheat_have += inv.get("WHEAT", 0)
        deficit = wheat_needed - wheat_have
        if deficit > 0:
            wheat_price = prices.get("WHEAT", 25)
            afford = int(money // wheat_price) if wheat_price > 0 else deficit
            n_buy = min(deficit, afford)
            if n_buy > 0:
                buy_orders.append(["BUY_PRODUCT", "WHEAT", n_buy])

    if hour == 2:
        needed_counts = {}
        for i, atype in enumerate(LIVESTOCK_TYPES):
            x, y = LIVESTOCK_POSITIONS[i]
            t = tiles[y][x]
            if not (isinstance(t, dict) and t.get("animal") == atype):
                needed_counts[atype] = needed_counts.get(atype, 0) + 1
        cash = money
        for atype, need in needed_counts.items():
            if day > LAST_BUY_DAY[atype]:
                continue
            have = shed.get(atype, 0)
            for inv in inventories:
                have += inv.get(atype, 0)
            to_buy = max(0, need - have)
            cost_each = ANIMAL_COST[atype]
            afford = int(cash // cost_each)
            n_buy = min(to_buy, afford)
            if n_buy > 0:
                buy_orders.append(["BUY_ANIMAL", atype, n_buy])
                cash -= n_buy * cost_each

    unlocked = me.get("unlocked_quadrants", ["NW"])
    n_unlocked = len(unlocked)
    if n_unlocked - 1 < len(LAND_ORDER):
        next_quadrant = LAND_ORDER[n_unlocked - 1]
        cost = LAND_COST[next_quadrant]
        # Not bought before its scheduled turn, but kept as a standing order
        # after that turn rather than a one-shot check -- a single missed
        # turn shouldn't permanently forfeit land. idea 4 (buy ASAP instead)
        # was tried and reverted -- see module docstring/constants above.
        if turn >= LAND_BUY_TURNS[next_quadrant] and money >= cost:
            buy_orders.append(["BUY_LAND"])

    if hour == 4:
        # Melon while still in-window; strawberry on the same footprint
        # once melon plantings stop (succession -- see module docstring).
        if day <= LAST_BUY_DAY["MELON"]:
            empty = sum(1 for x, y in SUCCESSION_POSITIONS if tiles[y][x] is None)
            have_seeds = seeds.get("MELON", 0)
            if empty > have_seeds:
                buy_orders.append(["BUY_SEED", "MELON", empty - have_seeds])
        elif day <= LAST_BUY_DAY["STRAWBERRY"]:
            empty = sum(1 for x, y in SUCCESSION_POSITIONS if tiles[y][x] is None)
            have_seeds = seeds.get("STRAWBERRY", 0)
            if empty > have_seeds:
                buy_orders.append(["BUY_SEED", "STRAWBERRY", empty - have_seeds])

    if hour == 5 and day <= LAST_BUY_DAY["WHEAT"]:
        empty = sum(1 for x, y in WHEAT_POSITIONS if tiles[y][x] is None)
        have_seeds = seeds.get("WHEAT", 0)
        if empty > have_seeds:
            buy_orders.append(["BUY_SEED", "WHEAT", empty - have_seeds])

    # sells-before-buys (so a same-turn sell could fund a same-turn BUY_LAND,
    # which every one of the 10 top-10 submissions relies on -- their own
    # turn-start money is below the land cost 100% of the time at their NE
    # purchase; kaggle_replays/PLAYBOOK_FINDINGS.md) was TRIED and REVERTED
    # together with the wheat-sell change above (n=20 paired, -$8.2k/-$8.4k,
    # same run). Likely cause, not yet isolated further: `maxMarketOrdersPerTurn`
    # caps processing at 10 orders/turn, extras silently dropped -- buy_orders
    # used to lead (HIRE up to 12 calls on peak days lands first and always
    # fits), so sells (this economy's is a handful of items) only displaced
    # already-low-priority late buys. Putting sells first instead means they
    # eat into that same 10-slot budget ahead of HIRE, plausibly starving
    # hires on exactly the high-hire days this already cash-starved schedule
    # can least afford (see Outcome section). A land-purchase-only sell
    # reorder (not a blanket one) would test that theory but wasn't attempted
    # this pass. buy_orders-then-sells kept.
    market = buy_orders + sells

    hands = me.get("hands", [])
    n_live, n_succ, n_wheat = role_split(len(hands))

    live_groups = chunk_indices(len(LIVESTOCK_POSITIONS), 1 + n_live)
    succ_groups = chunk_indices(len(SUCCESSION_POSITIONS), n_succ) if n_succ else []
    wheat_groups = chunk_indices(len(WHEAT_POSITIONS), n_wheat) if n_wheat else []

    fx, fy = me["farmer"]
    farmer_inv = inventories[0] if inventories else {}
    farmer_idxs = live_groups[0] if live_groups else []
    farmer_action = (
        livestock_action((fx, fy), farmer_inv, tiles, shed, farmer_idxs, LIVESTOCK_POSITIONS, LIVESTOCK_TYPES)
        if farmer_idxs else ["PASS"]
    )

    succession_crop = "MELON" if day <= LAST_BUY_DAY["MELON"] else "STRAWBERRY"
    succession_seed_count = seeds.get(succession_crop, 0)

    hands_actions = []
    for h_idx, hpos in enumerate(hands):
        unit_num = h_idx + 1
        hinv = inventories[unit_num] if unit_num < len(inventories) else {}
        pos = tuple(hpos)
        if unit_num < len(live_groups):
            idxs = live_groups[unit_num]
            hands_actions.append(
                livestock_action(pos, hinv, tiles, shed, idxs, LIVESTOCK_POSITIONS, LIVESTOCK_TYPES)
                if idxs else ["PASS"]
            )
        elif unit_num - len(live_groups) < len(succ_groups):
            idxs = succ_groups[unit_num - len(live_groups)]
            hands_actions.append(
                crop_action(succession_crop, CROP_MAX_YIELD_DAY[succession_crop], pos, day, tiles,
                            idxs, SUCCESSION_POSITIONS, succession_seed_count)
                if idxs else ["PASS"]
            )
        elif unit_num - len(live_groups) - len(succ_groups) < len(wheat_groups):
            idxs = wheat_groups[unit_num - len(live_groups) - len(succ_groups)]
            hands_actions.append(
                crop_action("WHEAT", CROP_MAX_YIELD_DAY["WHEAT"], pos, day, tiles,
                            idxs, WHEAT_POSITIONS, seeds.get("WHEAT", 0))
                if idxs else ["PASS"]
            )
        else:
            hands_actions.append(["PASS"])

    return {"farmer": farmer_action, "hands": hands_actions, "market": market}


def _demo():
    from kaggle_environments import make

    env = make("kaggriculture", configuration={"episodeSteps": 100}, debug=False)
    env.run([agent, "random"])
    final = env.steps[-1][0].observation["farms"][0]["money"]
    assert final >= 0
    print("leader_clone self-check OK, final money:", final)


def _run_ab():
    import json
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from harness import run_matches

    results = {}
    for opp in ["random", "starter"]:
        results[opp] = run_matches(agent, opp, n_episodes=8, episode_steps=720)
        print("leader_clone", "vs", opp, results[opp])
    out_path = Path(__file__).resolve().parent / "results" / "leader_clone.json"
    out_path.parent.mkdir(exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2)


if __name__ == "__main__":
    _demo()
