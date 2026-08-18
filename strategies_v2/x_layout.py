"""X strategy -- livestock strung along the board's diagonals for cross-
quadrant accessibility, melon filling the rest.

strategy.md: "X: Only if livestock access dominates density loss ... Accessible
livestock network; otherwise likely inferior to Ring." The two board
diagonals (x==y and x+y==9) pass through the shed hub and reach into every
quadrant, so tiles on them let units reach NW/NE/SW without detouring off the
direct path -- the tradeoff being land purchases (NE $1k, SW $2k) needed to
reach that network at all, and lower density than Ring's tight hub cluster.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine import (
    QUADRANT_TILES, chunk_indices, crop_action, last_buy_day, livestock_action,
    next_land_buy, sell_orders,
)

ANIMAL_MIX = {"COW": 14, "SHEEP": 8}
ANIMAL_COST = {"COW": 400, "SHEEP": 500}
LIVESTOCK_HANDS = 7
MELON_HANDS = 2
MAX_MELON_TILES = 19
MELON_YIELD_DAY = 10
TARGET_QUADRANTS = 3  # NW + NE + SW -- the diagonal network's 3 arms
SELL_MIN_PRICE_FRAC = 0.4
BASE_PRICE = {"MELON": 250, "MILK": 160, "WOOL": 200, "CARROT": 35}
LAST_BUY_DAY = {"COW": last_buy_day("COW"), "SHEEP": last_buy_day("SHEEP"), "MELON": last_buy_day("MELON")}
LAND_LAST_BUY_DAY = LAST_BUY_DAY["MELON"]


def _diagonal_tiles(qx, qy):
    """Both diagonals of the 5x5 quadrant whose top-left corner is (qx, qy)."""
    main = [(qx + i, qy + i) for i in range(5)]
    anti = [(qx + i, qy + 4 - i) for i in range(5)]
    seen, out = set(), []
    for p in main + anti:
        if p not in seen:
            seen.add(p)
            out.append(p)
    return out


def _livestock_types():
    seq = []
    for animal, count in ANIMAL_MIX.items():
        seq += [animal] * count
    return seq


LIVESTOCK_TYPES = _livestock_types()

_ALL_DIAG = _diagonal_tiles(0, 0) + _diagonal_tiles(5, 0) + _diagonal_tiles(0, 5)  # NW, NE, SW
LIVESTOCK_POSITIONS = _ALL_DIAG[: len(LIVESTOCK_TYPES)]

_claimed = set(LIVESTOCK_POSITIONS)
_ALL_TILES = QUADRANT_TILES["NW"] + QUADRANT_TILES["NE"] + QUADRANT_TILES["SW"]
MELON_POSITIONS = [p for p in _ALL_TILES if p not in _claimed][:MAX_MELON_TILES]

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

    if hour == 3 and day <= LAND_LAST_BUY_DAY:
        # X's core value proposition is reaching NE+SW, so land is bought
        # ahead of melon seed spend (but still after wheat/animals -- a
        # starved herd is unrecoverable, land is not).
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
    print("x_layout self-check OK, final money:", final)


def _run_ab():
    import json
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from harness import run_matches

    results = {}
    for opp in ["random", "starter"]:
        results[opp] = run_matches(agent, opp, n_episodes=8, episode_steps=720)
        print("x_layout", "vs", opp, results[opp])
    out_path = Path(__file__).resolve().parent / "results" / "x_layout.json"
    out_path.parent.mkdir(exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2)


if __name__ == "__main__":
    _demo()
