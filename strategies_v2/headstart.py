"""HEADSTART strategy -- aggressive early land expansion before herd-building.

strategy.md: "Aggressive early investment, then transition into efficient
production" (10/10 priority mode) -- directly testing H3 ("Early land + worker
investment compounds when payback occurs before the horizon closes"). Reuses
RING's exact tile layout/crew (the confirmed-best production math), and
changes exactly one thing: spend priority. RING buys animals before land
(land only gets whatever cash is left); HEADSTART buys land before animals,
securing NE capacity as early as possible even if it delays filling the herd.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine import crop_action, livestock_action, next_land_buy, sell_orders
import ring

ANIMAL_MIX = ring.ANIMAL_MIX
ANIMAL_COST = ring.ANIMAL_COST
LIVESTOCK_TYPES = ring.LIVESTOCK_TYPES
LIVESTOCK_POSITIONS = ring.LIVESTOCK_POSITIONS
LIVESTOCK_GROUPS = ring.LIVESTOCK_GROUPS
MELON_POSITIONS = ring.MELON_POSITIONS
MELON_GROUPS = ring.MELON_GROUPS
MELON_YIELD_DAY = ring.MELON_YIELD_DAY
N_HIRES = ring.N_HIRES
TARGET_QUADRANTS = ring.TARGET_QUADRANTS
SELL_MIN_PRICE_FRAC = ring.SELL_MIN_PRICE_FRAC
BASE_PRICE = ring.BASE_PRICE
LAST_BUY_DAY = ring.LAST_BUY_DAY
LAND_LAST_BUY_DAY = ring.LAND_LAST_BUY_DAY


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
        # HIRE is not gated by `investing` -- see ring.py's comment; hands
        # are re-hired fresh every day, not a one-time capacity investment.
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

    # The one deliberate difference from ring.py: land is bought BEFORE
    # animals, not after -- securing capacity ahead of herd size.
    if hour == 2 and day <= LAND_LAST_BUY_DAY:
        land = next_land_buy(me, money, TARGET_QUADRANTS)
        if land:
            buy_orders.append(land)

    if hour == 3:
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
    print("headstart self-check OK, final money:", final)


def _run_ab():
    import json
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from harness import run_matches

    results = {}
    for opp in ["random", "starter"]:
        results[opp] = run_matches(agent, opp, n_episodes=8, episode_steps=720)
        print("headstart", "vs", opp, results[opp])
    out_path = Path(__file__).resolve().parent / "results" / "headstart.json"
    out_path.parent.mkdir(exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2)


if __name__ == "__main__":
    _demo()
