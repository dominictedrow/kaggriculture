"""SOLID strategy -- dense single-quadrant crop block, no livestock.

strategy.md: "Solid is the strongest simple baseline because it minimizes
movement complexity and provides a clean melon-to-safe-crop transition" --
"Melon-heavy early phase -> wheat/carrot stabilization." Implemented as a
single contiguous NW block (no BUY_LAND, no shed-trip livestock overhead):
most tiles go to melon (the high-upside crop), a minority go to wheat/carrot
as a lower-volatility stabilizer, split spatially rather than by day so no
extra phase-tracking state is needed.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine import QUADRANT_TILES, chunk_indices, crop_action, last_buy_day, sell_orders

MELON_TILES = 18
WHEAT_TILES = 4
CARROT_TILES = 3  # 18+4+3 = 25 = all of NW
CROP_MAX_YIELD_DAY = {"MELON": 10, "WHEAT": 4, "CARROT": 3}  # RULES.md Object Types
SELL_MIN_PRICE_FRAC = 0.4
BASE_PRICE = {"MELON": 250, "MILK": 160, "WOOL": 200, "CARROT": 35}
# Per-crop cutoff, not one flat day -- melon (10-day time-to-yield) needs to
# stop far earlier than wheat/carrot (2-day) or it just buys unyieldable seed.
LAST_BUY_DAY = {"MELON": last_buy_day("MELON"), "WHEAT": last_buy_day("WHEAT"), "CARROT": last_buy_day("CARROT")}

_NW_FORWARD = QUADRANT_TILES["NW"]  # row-major, dense contiguous fill
MELON_POSITIONS = _NW_FORWARD[:MELON_TILES]
WHEAT_POSITIONS = _NW_FORWARD[MELON_TILES:MELON_TILES + WHEAT_TILES]
CARROT_POSITIONS = _NW_FORWARD[MELON_TILES + WHEAT_TILES:MELON_TILES + WHEAT_TILES + CARROT_TILES]

# Crew: farmer + hand0 split melon (2 units for 18 tiles, matching the
# proven ~9-tile/unit melon density ceiling); hand1 = wheat; hand2 = carrot.
MELON_GROUPS = chunk_indices(len(MELON_POSITIONS), 2)
N_HIRES = 3  # 1 extra melon hand + 1 wheat hand + 1 carrot hand


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
    prices = obs.get("market", {}).get("prices", {})

    buy_orders = []
    sells = sell_orders(shed, prices, BASE_PRICE, SELL_MIN_PRICE_FRAC, hold_exempt=())

    if hour == 0:
        # HIRE is not gated by any day cutoff -- see ring.py's comment;
        # hands are re-hired fresh every day, not a one-time investment.
        for _ in range(N_HIRES):
            buy_orders.append(["HIRE"])

    if hour == 1 and day <= LAST_BUY_DAY["MELON"]:
        empty_melon = sum(1 for x, y in MELON_POSITIONS if tiles[y][x] is None)
        have = seeds.get("MELON", 0)
        if empty_melon > have:
            buy_orders.append(["BUY_SEED", "MELON", empty_melon - have])

    if hour == 2 and day <= LAST_BUY_DAY["WHEAT"]:
        empty_wheat = sum(1 for x, y in WHEAT_POSITIONS if tiles[y][x] is None)
        have = seeds.get("WHEAT", 0)
        if empty_wheat > have:
            buy_orders.append(["BUY_SEED", "WHEAT", empty_wheat - have])

    if hour == 3 and day <= LAST_BUY_DAY["CARROT"]:
        empty_carrot = sum(1 for x, y in CARROT_POSITIONS if tiles[y][x] is None)
        have = seeds.get("CARROT", 0)
        if empty_carrot > have:
            buy_orders.append(["BUY_SEED", "CARROT", empty_carrot - have])

    market = buy_orders + sells

    fx, fy = me["farmer"]
    farmer_idxs = MELON_GROUPS[0] if MELON_GROUPS else []
    farmer_action = (
        crop_action("MELON", CROP_MAX_YIELD_DAY["MELON"], (fx, fy), day, tiles, farmer_idxs, MELON_POSITIONS, seeds.get("MELON", 0))
        if farmer_idxs else ["PASS"]
    )

    hands = me.get("hands", [])
    hands_actions = []
    for h_idx, hpos in enumerate(hands):
        pos = tuple(hpos)
        if h_idx == 0:
            idxs = MELON_GROUPS[1] if len(MELON_GROUPS) > 1 else []
            hands_actions.append(
                crop_action("MELON", CROP_MAX_YIELD_DAY["MELON"], pos, day, tiles, idxs, MELON_POSITIONS, seeds.get("MELON", 0))
                if idxs else ["PASS"]
            )
        elif h_idx == 1:
            idxs = list(range(len(WHEAT_POSITIONS)))
            hands_actions.append(
                crop_action("WHEAT", CROP_MAX_YIELD_DAY["WHEAT"], pos, day, tiles, idxs, WHEAT_POSITIONS, seeds.get("WHEAT", 0))
                if idxs else ["PASS"]
            )
        elif h_idx == 2:
            idxs = list(range(len(CARROT_POSITIONS)))
            hands_actions.append(
                crop_action("CARROT", CROP_MAX_YIELD_DAY["CARROT"], pos, day, tiles, idxs, CARROT_POSITIONS, seeds.get("CARROT", 0))
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
    print("solid self-check OK, final money:", final)


def _run_ab():
    import json
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from harness import run_matches

    results = {}
    for opp in ["random", "starter"]:
        results[opp] = run_matches(agent, opp, n_episodes=8, episode_steps=720)
        print("solid", "vs", opp, results[opp])
    out_path = Path(__file__).resolve().parent / "results" / "solid.json"
    out_path.parent.mkdir(exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2)


if __name__ == "__main__":
    _demo()
