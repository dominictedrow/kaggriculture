"""Shared mechanics for strategies_v2/*.py.

Movement, livestock-unit logic, and one-time-crop-unit logic, factored out of
strategy_follower.py so each strategy script (ring/solid/checker/x_layout/
headstart) only has to define its own tile layout and buy policy, not
re-derive PLACE/FEED/HARVEST/PLANT/WATER/DIG rules. Positions/types are
passed in as arguments (no module-level globals) so the same functions serve
every layout.
"""

SHED_ADJACENT = {(4, 4), (5, 4), (4, 5), (5, 5)}
ANIMAL_STRUCTURE = "PASTURE"

QUADRANT_TILES = {
    "NW": [(x, y) for y in range(0, 5) for x in range(0, 5)],
    "NE": [(x, y) for y in range(0, 5) for x in range(5, 10)],
    "SW": [(x, y) for y in range(5, 10) for x in range(0, 5)],
    "SE": [(x, y) for y in range(5, 10) for x in range(5, 10)],
}
# RULES.md: NE/SW/SE unlock via BUY_LAND for $1k/$2k/$4k respectively, always
# in that order regardless of which BUY_LAND call triggers it.
LAND_ORDER = ["NE", "SW", "SE"]
LAND_COST = {"NE": 1000, "SW": 2000, "SE": 4000}

# kaggriculture README.md Object Types table -- days from BUY_ANIMAL/PLANT to
# the first (for animals: only) unit of output. Season is 30 days, 0-indexed
# (days 0-29), so buying/planting after `LAST_SEASON_DAY - time_to_first`
# can never produce a single yield before the season ends -- pure sunk cost.
# No extra logistics buffer: BUY_SEED/BUY_ANIMAL are market orders decoupled
# from hand position, and for crops specifically this cutoff is hit on every
# replant cycle, not just the opening buy (a melon tile that finishes
# harvest -> decay -> dig around day 12 needs to be replantable right up
# through day 19 -- a buffer here silently kills replant cycles that would
# have finished comfortably within the season; verified empirically: a
# 2-day buffer left 10/18 melon tiles idle for the last several days).
LAST_SEASON_DAY = 29
TIME_TO_FIRST_YIELD = {"MELON": 10, "WHEAT": 2, "CARROT": 2, "COW": 8, "SHEEP": 6}


def last_buy_day(item):
    """Last day it's still worth spending on `item` -- past this, the
    purchase can't finish producing even one unit before season end."""
    return LAST_SEASON_DAY - TIME_TO_FIRST_YIELD[item]


def step_toward(pos, target):
    x, y = pos
    tx, ty = target
    if x < tx:
        return "EAST"
    if x > tx:
        return "WEST"
    if y < ty:
        return "SOUTH"
    if y > ty:
        return "NORTH"
    return None


def nearest_step(pos, positions):
    """Step toward the closest of `positions` (Manhattan) -- every wasted
    step is an action turn not spent watering/feeding/harvesting."""
    if not positions:
        return None
    ux, uy = pos
    target = min(positions, key=lambda p: abs(p[0] - ux) + abs(p[1] - uy))
    return step_toward(pos, target)


def chunk_indices(n_items, n_groups):
    """Split range(n_items) into n_groups contiguous, near-equal chunks."""
    if n_groups <= 0:
        return []
    base, extra = divmod(n_items, n_groups)
    groups, start = [], 0
    for i in range(n_groups):
        size = base + (1 if i < extra else 0)
        groups.append(list(range(start, start + size)))
        start += size
    return groups


def next_land_buy(me, money, target_quadrants):
    """Return ["BUY_LAND"] if the next quadrant (in LAND_ORDER) is affordable
    and we haven't yet reached target_quadrants unlocked, else None."""
    unlocked = me.get("unlocked_quadrants", ["NW"])
    n = len(unlocked)
    if n >= target_quadrants or n > len(LAND_ORDER):
        return None
    cost = LAND_COST[LAND_ORDER[n - 1]]
    return ["BUY_LAND"] if money >= cost else None


# ---- Livestock unit action (adapted from strategy_follower.py) ------------

def livestock_action(pos, inv, tiles, shed, idxs, positions, types):
    ux, uy = pos
    cur_idx = next((i for i in idxs if positions[i] == (ux, uy)), None)
    if cur_idx is not None:
        atype = types[cur_idx]
        x, y = positions[cur_idx]
        tile = tiles[y][x]
        if tile is None:
            return ["BUILD_PASTURE"]
        if isinstance(tile, dict) and tile.get("kind") == ANIMAL_STRUCTURE and not tile.get("animal"):
            if inv.get(atype, 0) > 0:
                return ["PLACE", atype]
        elif isinstance(tile, dict) and tile.get("animal") == atype:
            if not tile["fed_today"]:
                if inv.get("WHEAT", 0) > 0:
                    return ["FEED"]
            elif tile["yield_units"] > 0:
                return ["HARVEST"]
            elif tile["fertilizer_available"]:
                return ["COLLECT_FERTILIZER"]
            elif not tile["cared_today"]:
                return ["CARE"]

    if pos in SHED_ADJACENT:
        wheat_needed = len(idxs)
        if wheat_needed > inv.get("WHEAT", 0) and shed.get("WHEAT", 0) > 0:
            n = min(shed["WHEAT"], wheat_needed - inv.get("WHEAT", 0))
            if n > 0:
                return ["PICKUP", "WHEAT", n]
        empty_needed = {}
        for i in idxs:
            atype = types[i]
            x, y = positions[i]
            t = tiles[y][x]
            if isinstance(t, dict) and t.get("kind") == ANIMAL_STRUCTURE and not t.get("animal"):
                empty_needed[atype] = empty_needed.get(atype, 0) + 1
        for atype, cnt in empty_needed.items():
            need = cnt - inv.get(atype, 0)
            avail = shed.get(atype, 0)
            if need > 0 and avail > 0:
                return ["PICKUP", atype, min(need, avail)]

    if pos not in SHED_ADJACENT:
        unfed_remaining = 0
        missing_animal = False
        for i in idxs:
            atype = types[i]
            x, y = positions[i]
            t = tiles[y][x]
            if isinstance(t, dict) and t.get("animal") == atype:
                if not t["fed_today"]:
                    unfed_remaining += 1
            elif isinstance(t, dict) and t.get("kind") == ANIMAL_STRUCTURE and not t.get("animal"):
                if inv.get(atype, 0) == 0:
                    missing_animal = True
        if unfed_remaining > inv.get("WHEAT", 0) or missing_animal:
            target = min(SHED_ADJACENT, key=lambda p: abs(p[0] - ux) + abs(p[1] - uy))
            step = step_toward(pos, target)
            if step:
                return [step]

    feed_needy = []
    other_needy = []
    for i in idxs:
        atype = types[i]
        x, y = positions[i]
        t = tiles[y][x]
        if t is None:
            other_needy.append((x, y))
        elif isinstance(t, dict) and t.get("kind") == ANIMAL_STRUCTURE and not t.get("animal"):
            if inv.get(atype, 0) > 0:
                other_needy.append((x, y))
        elif isinstance(t, dict) and t.get("animal") == atype:
            if not t["fed_today"] and inv.get("WHEAT", 0) > 0:
                feed_needy.append((x, y))
            elif t["yield_units"] > 0:
                other_needy.append((x, y))
            elif t["fertilizer_available"]:
                other_needy.append((x, y))
            elif t["fed_today"] and not t["cared_today"]:
                other_needy.append((x, y))
    step = nearest_step(pos, feed_needy) or nearest_step(pos, other_needy)
    if step:
        return [step]
    return ["PASS"]


# ---- One-time-crop unit action (melon/wheat/carrot share this mechanic) ---

def crop_action(crop, max_yield_day, pos, day, tiles, idxs, positions, seed_count):
    """seed_count must be checked before treating an empty tile as
    plantable -- once BUY_SEED stops (season-end cutoff, or just a bad
    day), a hand standing on its assigned empty tile would otherwise return
    PLANT every turn forever (a silent no-op with no seed) and never move to
    tend its other tiles for the rest of the game. Verified this was a real,
    not theoretical, multi-thousand-dollar bug once a seed cutoff made empty
    unplantable tiles common instead of rare."""
    ux, uy = pos
    cur_idx = next((i for i in idxs if positions[i] == (ux, uy)), None)
    if cur_idx is not None:
        x, y = positions[cur_idx]
        tile = tiles[y][x]
        if tile is None:
            if seed_count > 0:
                return ["PLANT", crop]
            # no seed -- fall through to the needy scan instead of getting
            # stuck spamming a no-op PLANT here for the rest of the season
        # A crop pool can reach into a not-yet-bought quadrant (locked tiles
        # are passable); "LOCKED" is a plain string, not a dict.
        elif isinstance(tile, dict):
            if tile.get("kind") == "WEED":
                return ["DIG"]
            if tile.get("kind") == "PLANT":
                age = day - tile["planted_day"]
                if age >= max_yield_day and tile["yield_units"] > 0:
                    return ["HARVEST"]
                if not tile["watered_today"]:
                    return ["WATER"]

    water_needy = []
    other_needy = []
    for i in idxs:
        x, y = positions[i]
        t = tiles[y][x]
        if t is None:
            if seed_count > 0:
                other_needy.append((x, y))
        elif isinstance(t, dict) and t.get("kind") == "WEED":
            other_needy.append((x, y))
        elif isinstance(t, dict) and t.get("kind") == "PLANT":
            age = day - t["planted_day"]
            if age >= max_yield_day and t["yield_units"] > 0:
                other_needy.append((x, y))
            elif not t["watered_today"]:
                water_needy.append((x, y))
    step = nearest_step(pos, water_needy) or nearest_step(pos, other_needy)
    if step:
        return [step]
    return ["PASS"]


def sell_orders(shed, prices, base_price, sell_min_price_frac, hold_exempt=("WHEAT",)):
    """Dump every shed item except `hold_exempt`, holding back (not selling)
    anything priced below sell_min_price_frac * its base price -- unless the
    shed is nearly full (>=90), where overflow loss beats a cheap sale."""
    orders = []
    for item, n in list(shed.items()):
        if n <= 0 or item in hold_exempt:
            continue
        base = base_price.get(item)
        cur = prices.get(item)
        if sell_min_price_frac > 0 and base and cur is not None and cur < sell_min_price_frac * base and n < 90:
            continue
        orders.append(["SELL", item, n])
    return orders


def _demo():
    assert step_toward((0, 0), (2, 0)) == "EAST"
    assert step_toward((0, 0), (0, 2)) == "SOUTH"
    assert step_toward((0, 0), (0, 0)) is None
    assert chunk_indices(5, 2) == [[0, 1, 2], [3, 4]]
    assert next_land_buy({"unlocked_quadrants": ["NW"]}, 999, 2) is None
    assert next_land_buy({"unlocked_quadrants": ["NW"]}, 1000, 2) == ["BUY_LAND"]
    assert next_land_buy({"unlocked_quadrants": ["NW", "NE"]}, 5000, 2) is None
    print("engine self-check OK")


if __name__ == "__main__":
    _demo()
