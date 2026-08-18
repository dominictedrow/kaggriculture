"""RING strategy -- central livestock, crops radiating outward.

strategy.md ("Strategy Library"): "Central livestock with crops around it;
preserve density." The shed hub ((4,4)/(5,4)/(4,5)/(5,5)) sits at the exact
center of the 10x10 board, so "central" tiles are the ones nearest that hub
by Manhattan distance, across NW+NE. Livestock claims the closest ring of
tiles to the hub; melon fills outward from there. This is the same production
math as the confirmed-best submitted build (strategy_follower.py) --
11 COW / 6 SHEEP, 6 hands, 2 melon hands -- just with hub-distance tile
selection made explicit instead of an NW-backward-scan approximation of it.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine import (
    QUADRANT_TILES, chunk_indices, crop_action, last_buy_day, livestock_action,
    next_land_buy, sell_orders,
)

ANIMAL_MIX = {"COW": 11, "SHEEP": 6}
ANIMAL_COST = {"COW": 400, "SHEEP": 500}
LIVESTOCK_HANDS = 6
MELON_HANDS = 2
MAX_MELON_TILES = 19
MELON_YIELD_DAY = 10
TARGET_QUADRANTS = 2  # NW + NE -- enough room for the hub ring plus melon
SELL_MIN_PRICE_FRAC = 0.4
BASE_PRICE = {"MELON": 250, "MILK": 160, "WOOL": 200, "CARROT": 35}
LAST_BUY_DAY = {"COW": last_buy_day("COW"), "SHEEP": last_buy_day("SHEEP"), "MELON": last_buy_day("MELON")}
# LAND is worthwhile only if there's still time to buy+place/plant something
# on the room it unlocks -- MELON's cutoff is the tightest thing it enables.
LAND_LAST_BUY_DAY = LAST_BUY_DAY["MELON"]

HUB = (4.5, 4.5)


def _livestock_types():
    seq = []
    for animal, count in ANIMAL_MIX.items():
        seq += [animal] * count
    return seq


LIVESTOCK_TYPES = _livestock_types()

# NW tiles first (already owned at game start), then NE -- within each
# quadrant, nearest the shed hub first. Sorting NW+NE together by raw
# hub-distance (the original version of this) interleaved locked NE tiles
# into nearly every hand's chunk, leaving ~half the herd unplaceable for the
# ~9 days it takes to afford NE -- exhausting NW first keeps the whole herd
# workable from turn 1, same as the confirmed-best build, while still
# ordering each quadrant's own tiles by hub-distance for the "ring" shape.
_NW_SET = set(QUADRANT_TILES["NW"])
_HUB_SORTED = sorted(
    QUADRANT_TILES["NW"] + QUADRANT_TILES["NE"],
    key=lambda p: (0 if p in _NW_SET else 1, abs(p[0] - HUB[0]) + abs(p[1] - HUB[1]), p[1], p[0]),
)

LIVESTOCK_POSITIONS = _HUB_SORTED[: len(LIVESTOCK_TYPES)]
_claimed = set(LIVESTOCK_POSITIONS)
MELON_POSITIONS = [p for p in _HUB_SORTED if p not in _claimed][:MAX_MELON_TILES]

LIVESTOCK_GROUPS = chunk_indices(len(LIVESTOCK_POSITIONS), 1 + LIVESTOCK_HANDS)
MELON_GROUPS = chunk_indices(len(MELON_POSITIONS), MELON_HANDS)
N_HIRES = LIVESTOCK_HANDS + MELON_HANDS


def agent(obs):
    player = obs["player"]
    me = obs["farms"][player]
    private = obs["private"]
    day = obs["day"]
    hour = obs["hour"]
    tiles = me["tiles"]
    shed = private.get("shed", {})
    seeds = private.get("seeds", {})
    money = me["money"]
    inventories = private.get("inventories", [{}])
    prices = obs.get("market", {}).get("prices", {})

    buy_orders = []
    sells = sell_orders(shed, prices, BASE_PRICE, SELL_MIN_PRICE_FRAC)

    if hour == 0:
        # HIRE is not gated by `investing` -- hands are re-hired fresh every
        # day (RULES.md: they disappear at day-end), so this isn't new
        # capacity investment, it's the daily cost of keeping the existing
        # crew operating. Gating it here would drop the whole crew to just
        # the farmer for the last few days -- exactly when the herd/crops
        # are most mature and there's the most to lose.
        for _ in range(N_HIRES):
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
            # Per-animal cutoff -- COW (8-day time-to-first-yield) stops
            # earlier than SHEEP (6 days); a flat day-of-season check would
            # keep buying COWs that can never produce even once.
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

    if hour == 3 and day <= LAND_LAST_BUY_DAY:
        land = next_land_buy(me, money, TARGET_QUADRANTS)
        if land:
            buy_orders.append(land)

    if hour == 4 and day <= LAST_BUY_DAY["MELON"]:
        empty_melon = sum(1 for x, y in MELON_POSITIONS if tiles[y][x] is None)
        have_seeds = seeds.get("MELON", 0)
        if empty_melon > have_seeds:
            buy_orders.append(["BUY_SEED", "MELON", empty_melon - have_seeds])

    market = buy_orders + sells

    fx, fy = me["farmer"]
    farmer_inv = inventories[0] if inventories else {}
    farmer_idxs = LIVESTOCK_GROUPS[0] if LIVESTOCK_GROUPS else []
    farmer_action = (
        livestock_action((fx, fy), farmer_inv, tiles, shed, farmer_idxs, LIVESTOCK_POSITIONS, LIVESTOCK_TYPES)
        if farmer_idxs else ["PASS"]
    )

    hands = me.get("hands", [])
    hands_actions = []
    for h_idx, hpos in enumerate(hands):
        unit_num = h_idx + 1
        hinv = inventories[unit_num] if unit_num < len(inventories) else {}
        if unit_num < len(LIVESTOCK_GROUPS):
            idxs = LIVESTOCK_GROUPS[unit_num]
            hands_actions.append(
                livestock_action(tuple(hpos), hinv, tiles, shed, idxs, LIVESTOCK_POSITIONS, LIVESTOCK_TYPES)
                if idxs else ["PASS"]
            )
        elif unit_num - len(LIVESTOCK_GROUPS) < len(MELON_GROUPS):
            idxs = MELON_GROUPS[unit_num - len(LIVESTOCK_GROUPS)]
            hands_actions.append(
                crop_action("MELON", MELON_YIELD_DAY, tuple(hpos), day, tiles, idxs, MELON_POSITIONS, seeds.get("MELON", 0))
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
    print("ring self-check OK, final money:", final)


def _run_ab():
    import json
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from harness import run_matches

    results = {}
    for opp in ["random", "starter"]:
        results[opp] = run_matches(agent, opp, n_episodes=8, episode_steps=720)
        print("ring", "vs", opp, results[opp])
    out_path = Path(__file__).resolve().parent / "results" / "ring.json"
    out_path.parent.mkdir(exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2)


if __name__ == "__main__":
    _demo()
