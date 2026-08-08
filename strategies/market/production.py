"""Fixed production baseline shared, UNCHANGED, by every market-tactic config.

A single farmer (no hired hands, no fertilizer, no animals) walks a fixed
12-tile loop in the NW quadrant: 6 WHEAT tiles then 6 CARROT tiles. Each
tile is planted, watered daily, and harvested at its `max_yield_day` (peak
unfertilized yield: 4 for wheat, 3 for carrot), then replanted. Seed buys
are handled here (mandatory upkeep, not a "market tactic"); SELL/BUY_PRODUCT
decisions are NOT made here -- that's the pluggable policy layer in
policy.py / agent.py.

The farmer/hand position resets to the shed-adjacent spawn tile (4,4) at
the end of every day, so the loop is deliberately a tight ring around that
spawn point (max Chebyshev distance 3) rather than spread across the whole
quadrant -- otherwise the daily walk back out to resume the loop dominates
the turn budget and plants die of neglect before they can be harvested.

This is deliberately simple and reused unchanged across every config in
this study, so any difference in results is attributable to the market
policy layered on top, not to production changes.
"""

SEED_COST = {"WHEAT": 10, "CARROT": 20}
MAX_YIELD_DAY = {"WHEAT": 4, "CARROT": 3}

# Snake path through a 4x3 block of tiles centered on the (4,4) spawn tile,
# so every day's walk back into the loop is short. Consecutive tiles are
# orthogonally adjacent except the wraparound from the last back to the
# first, which the generic move-toward-target step just takes a few extra
# turns to cover.
PATH = [
    (1, 2), (2, 2), (3, 2), (4, 2),
    (4, 3), (3, 3), (2, 3), (1, 3),
    (1, 4), (2, 4), (3, 4), (4, 4),
]
CROP_FOR = ["WHEAT"] * 6 + ["CARROT"] * 6


class BaselineFarmer:
    """Stateful per-episode walker. Call .step(obs) each turn."""

    def __init__(self):
        self.idx = 0

    def step(self, obs):
        if obs.get("step", 0) == 0:
            self.idx = 0  # fresh episode; same object may be reused across episodes

        player = obs["player"]
        me = obs["farms"][player]
        private = obs["private"]
        day = obs["day"]
        seeds = private["seeds"]
        market_orders = []

        # At most 2 iterations: one to notice "nothing to do here today" and
        # advance idx, one to act on (or move toward) the new target -- this
        # avoids wasting a whole turn on a bare PASS every time a tile is
        # already fully handled for the day.
        for _ in range(2):
            fx, fy = me["farmer"]
            i = self.idx % len(PATH)
            tx, ty = PATH[i]
            crop = CROP_FOR[i]

            if (fx, fy) != (tx, ty):
                if fx < tx:
                    action = ["EAST"]
                elif fx > tx:
                    action = ["WEST"]
                elif fy < ty:
                    action = ["SOUTH"]
                else:
                    action = ["NORTH"]
                return action, market_orders

            tile = me["tiles"][fy][fx]

            if tile is None:
                if seeds.get(crop, 0) <= 0:
                    if me["money"] >= SEED_COST[crop]:
                        market_orders.append(["BUY_SEED", crop, 1])
                    return ["PASS"], market_orders
                return ["PLANT", crop], market_orders

            if isinstance(tile, dict) and tile.get("kind") == "WEED":
                return ["DIG"], market_orders

            if isinstance(tile, dict) and tile.get("kind") == "PLANT" and tile.get("crop") == crop:
                if not tile["watered_today"]:
                    return ["WATER"], market_orders
                age = day - tile["planted_day"]
                if age >= MAX_YIELD_DAY[crop] and tile.get("yield_units", 0) > 0:
                    self.idx += 1
                    return ["HARVEST"], market_orders
                # Watered already, not ready yet -- move on to the next tile
                # this same turn instead of burning a turn on PASS.
                self.idx += 1
                continue

            # Unexpected occupant (e.g. mid-transition); do nothing this turn.
            return ["PASS"], market_orders

        return ["PASS"], market_orders
