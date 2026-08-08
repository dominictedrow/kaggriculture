"""Fixed production task shared by every labor/land config in this sweep.

FIXED WHEAT LOOP (identical for every config we test -- only hiring/land
policy varies on top of this):

  Every active unit (main farmer + any hired hands) independently runs the
  same loop on whichever tile it is nearest to within its assigned tile
  list:
    - standing on a WHEAT plant with age >= 4 (max_yield_day)  -> HARVEST
    - standing on a WHEAT plant not watered today               -> WATER
    - standing on a WEED                                        -> DIG
    - standing on an empty (None) tile with a seed available    -> PLANT WHEAT
    - otherwise, move one step toward the nearest tile (in its assigned
      list) that needs one of the above actions, priority
      harvest > water > dig-weed > plant, ties broken by Manhattan distance.
    - if nothing in its assigned list needs action, PASS.

  Market side (every turn): sell all WHEAT sitting in the shed, and top up
  the WHEAT seed stock to `n_active_units` so every unit can always PLANT
  the moment it stands on an empty tile (the engine validates PLANT against
  the seed pool as it existed *before* this turn's BUY_SEED order, so the
  buffer has to be pre-funded a turn ahead -- topping up every turn keeps it
  full from turn 2 onward).

  Tile allocation across units ("who works which tile") is itself one of
  the strategy dimensions under test (see ALLOCATION_MODES below), but the
  per-unit wheat-loop behavior itself never changes.
"""

WHEAT_FIRST_YIELD_DAY = 2
WHEAT_MAX_YIELD_DAY = 4
WHEAT_SEED_COST = 10

ALLOCATION_MODES = ("stripe", "quadrant", "nearest")


def _quadrant_of(x, y, half):
    return ("N" if y < half else "S") + ("W" if x < half else "E")


def unlocked_tiles(tiles2d, board_size):
    """All non-LOCKED tile coords, row-major order."""
    out = []
    for y in range(board_size):
        row = tiles2d[y]
        for x in range(board_size):
            if row[x] != "LOCKED":
                out.append((x, y))
    return out


def assign_tiles(tiles2d, board_size, n_units, mode):
    """Split unlocked tiles among n_units units. Returns list[list[(x,y)]]."""
    tiles = unlocked_tiles(tiles2d, board_size)
    if n_units <= 0:
        return []
    if mode == "quadrant":
        half = board_size // 2
        buckets = {"NW": [], "NE": [], "SW": [], "SE": []}
        for (x, y) in tiles:
            buckets[_quadrant_of(x, y, half)].append((x, y))
        quads = [buckets[q] for q in ("NW", "NE", "SW", "SE") if buckets[q]]
        out = [[] for _ in range(n_units)]
        for qi, qtiles in enumerate(quads):
            unit = qi % n_units
            out[unit].extend(qtiles)
        return out
    # "stripe" (default) and "nearest" (pool handled by caller) both start
    # from an even row-major split; "nearest" callers pass the full pool
    # per-unit instead of using this split.
    out = [[] for _ in range(n_units)]
    for i, t in enumerate(tiles):
        out[i % n_units].append(t)
    return out


def _tile_priority(tile, day):
    """Return priority int (lower = more urgent) or None if tile needs nothing."""
    if isinstance(tile, dict):
        if tile.get("kind") == "PLANT" and tile.get("crop") == "WHEAT":
            age = day - tile["planted_day"]
            if age >= WHEAT_MAX_YIELD_DAY:
                return 0  # harvest
            if not tile["watered_today"]:
                return 1  # water
            return None  # growing, already watered today
        if tile.get("kind") == "WEED":
            return 2  # dig
        return None  # some other structure, not our concern
    if tile is None:
        return 3  # plant
    return None


def _pick_target(pos, tiles2d, day, tile_list):
    x0, y0 = pos
    best = None
    best_key = None
    for (x, y) in tile_list:
        prio = _tile_priority(tiles2d[y][x], day)
        if prio is None:
            continue
        dist = abs(x - x0) + abs(y - y0)
        key = (prio, dist)
        if best_key is None or key < best_key:
            best_key = key
            best = (x, y)
    return best


def _step_toward(pos, target):
    x0, y0 = pos
    x1, y1 = target
    dx, dy = x1 - x0, y1 - y0
    if dx == 0 and dy == 0:
        return None
    if abs(dx) >= abs(dy) and dx != 0:
        return "EAST" if dx > 0 else "WEST"
    return "SOUTH" if dy > 0 else "NORTH"


def unit_action(pos, tiles2d, day, tile_list):
    target = _pick_target(pos, tiles2d, day, tile_list)
    if target is None:
        return ["PASS"]
    if target == tuple(pos):
        tile = tiles2d[pos[1]][pos[0]]
        if isinstance(tile, dict):
            if tile.get("kind") == "PLANT":
                age = day - tile["planted_day"]
                if age >= WHEAT_MAX_YIELD_DAY:
                    return ["HARVEST"]
                if not tile["watered_today"]:
                    return ["WATER"]
            elif tile.get("kind") == "WEED":
                return ["DIG"]
        elif tile is None:
            return ["PLANT", "WHEAT"]
        return ["PASS"]
    d = _step_toward(pos, target)
    return [d] if d else ["PASS"]


def unit_actions_for_turn(farm, day, allocation):
    """Compute (farmer_action, [hand_actions...]) for this turn."""
    board_size = len(farm["tiles"])
    tiles2d = farm["tiles"]
    positions = [tuple(farm["farmer"])] + [tuple(h) for h in farm["hands"]]
    n_units = len(positions)
    if n_units == 0:
        return ["PASS"], []

    if allocation == "nearest":
        pool = unlocked_tiles(tiles2d, board_size)
        actions = []
        taken = set()
        for pos in positions:
            candidates = [t for t in pool if t not in taken]
            target = _pick_target(pos, tiles2d, day, candidates)
            if target is not None:
                taken.add(target)
                # Reuse unit_action's execute-in-place logic via a 1-tile list
                # trick: if target == pos, act; else move.
                if target == pos:
                    tile = tiles2d[pos[1]][pos[0]]
                    if isinstance(tile, dict):
                        if tile.get("kind") == "PLANT":
                            age = day - tile["planted_day"]
                            act = ["HARVEST"] if age >= WHEAT_MAX_YIELD_DAY else ["WATER"]
                        else:
                            act = ["DIG"]
                    else:
                        act = ["PLANT", "WHEAT"]
                else:
                    d = _step_toward(pos, target)
                    act = [d] if d else ["PASS"]
            else:
                act = ["PASS"]
            actions.append(act)
    else:
        assignment = assign_tiles(tiles2d, board_size, n_units, allocation)
        actions = [unit_action(pos, tiles2d, day, assignment[i]) for i, pos in enumerate(positions)]

    return actions[0], actions[1:]


def market_orders(farm, private, n_units, order_budget):
    """Sell shed wheat + top up seed buffer. Returns list of market orders,
    consuming at most order_budget slots (leaves room for hire/land orders)."""
    orders = []
    shed_wheat = private.get("shed", {}).get("WHEAT", 0)
    if shed_wheat > 0 and order_budget > 0:
        orders.append(["SELL", "WHEAT", shed_wheat])
        order_budget -= 1

    current_seeds = private.get("seeds", {}).get("WHEAT", 0)
    target = max(n_units, 1)
    need = target - current_seeds
    if need > 0 and order_budget > 0:
        affordable = int(farm["money"] // WHEAT_SEED_COST)
        buy_n = min(need, affordable)
        if buy_n > 0:
            orders.append(["BUY_SEED", "WHEAT", buy_n])
            order_budget -= 1

    return orders, order_budget
