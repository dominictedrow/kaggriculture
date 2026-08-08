"""Generic, config-driven crop-strategy agent for Kaggriculture.

make_agent(config) returns a stateless obs -> action callable. All behavior
(tile density, crop mix, watering/fertilize/harvest timing, land expansion,
selling, hiring) is driven by the config dict -- no per-strategy code needed.

The agent never visits the shed: harvested crops land in inventory and are
auto-dropped to the shed at end-of-day by the engine itself, and every
market op (BUY_SEED/SELL/BUY_LAND/BUY_PRODUCT/HIRE) is position-independent.
The only reason to visit a shed-adjacent tile is to PICKUP fertilizer, and
the farmer already spawns on one each morning.
"""

from kaggle_environments.envs.kaggriculture.kaggriculture import CROPS

BOARD_SIZE = 10
HALF = BOARD_SIZE // 2
QUADRANT_ORDER = ["NW", "NE", "SW", "SE"]


def _quadrant_of(x, y):
    return ("N" if y < HALF else "S") + ("W" if x < HALF else "E")


def _quadrant_cells(q):
    xs = range(0, HALF) if "W" in q else range(HALF, BOARD_SIZE)
    ys = range(0, HALF) if "N" in q else range(HALF, BOARD_SIZE)
    return [(x, y) for y in ys for x in xs]


# Fixed global scan order: NW's 25 cells, then NE's, then SW's, then SE's.
FULL_SCAN_ORDER = [cell for q in QUADRANT_ORDER for cell in _quadrant_cells(q)]


def window_start(crop):
    return (CROPS[crop]["max_yield_day"] + 1) // 2


def _tile_plan(unlocked_quadrants, max_tiles, crop_mix):
    """Ordered list of (x, y, crop) for up to max_tiles cells drawn from
    currently unlocked quadrants, in FULL_SCAN_ORDER, crops cycling through
    crop_mix (a list of (crop, weight) -- expanded into a repeating pattern).
    """
    pattern = []
    for crop, weight in crop_mix:
        pattern.extend([crop] * weight)
    if not pattern:
        return []
    unlocked = set(unlocked_quadrants)
    cells = [c for c in FULL_SCAN_ORDER if _quadrant_of(*c) in unlocked][:max_tiles]
    return [(x, y, pattern[i % len(pattern)]) for i, (x, y) in enumerate(cells)]


def _step_toward(fx, fy, tx, ty):
    dx, dy = tx - fx, ty - fy
    if dx > 0:
        return "EAST"
    if dx < 0:
        return "WEST"
    if dy > 0:
        return "SOUTH"
    if dy < 0:
        return "NORTH"
    return "PASS"


def _harvest_threshold(crop, harvest_at):
    cd = CROPS[crop]
    return cd["first_yield_day"] if harvest_at == "first" else cd["max_yield_day"]


def _tile_action(tile, crop, day, harvest_at, fertilize, have_fertilizer):
    """Decide the single action to take while standing on a plan tile.
    Returns one of: "PLANT", "WATER", "HARVEST", "FERTILIZE", "DIG", None.
    """
    if tile is None:
        return "PLANT"
    if isinstance(tile, dict) and tile.get("kind") == "WEED":
        return "DIG"
    if isinstance(tile, dict) and tile.get("kind") == "PLANT":
        age = day - tile["planted_day"]
        threshold = _harvest_threshold(tile["crop"], harvest_at)
        if tile["yield_units"] > 0 and age >= CROPS[tile["crop"]]["first_yield_day"] and age >= threshold:
            return "HARVEST"
        if (
            fertilize == "bonus"
            and have_fertilizer
            and age == window_start(tile["crop"])
            and tile.get("fertilized_until_day", -1) < day
        ):
            return "FERTILIZE"
        if not tile["watered_today"]:
            return "WATER"
        return None
    return None


def _needs_action(tile, crop, day, harvest_at, fertilize):
    return _tile_action(tile, crop, day, harvest_at, fertilize, have_fertilizer=True) is not None


def _fertilizer_demand(farm, plan, target_day):
    """Count plan tiles that will enter the bonus window on target_day and still need fertilizing."""
    n = 0
    for x, y, crop in plan:
        tile = farm["tiles"][y][x]
        if (
            isinstance(tile, dict)
            and tile.get("kind") == "PLANT"
            and target_day - tile["planted_day"] == window_start(tile["crop"])
            and tile.get("fertilized_until_day", -1) < target_day
        ):
            n += 1
    return n


def make_agent(config):
    """config keys:
      crop_mix:   [(crop, weight), ...]
      max_tiles:  int, density cap across the whole board (<=100)
      harvest_at: "first" | "max"
      fertilize:  "never" | "bonus"
      land:       "never" | "asap" | list[int] (days to attempt BUY_LAND, one per call)
      sell:       "dump" | ("batch", n)
      hire:       0 | 1
    """
    crop_mix = config["crop_mix"]
    max_tiles = config["max_tiles"]
    harvest_at = config.get("harvest_at", "first")
    fertilize = config.get("fertilize", "never")
    land = config.get("land", "never")
    sell = config.get("sell", "dump")
    hire = config.get("hire", 0)
    crops_in_mix = [c for c, _ in crop_mix]

    def agent(obs):
        player = obs["player"]
        day = obs["day"]
        hour = obs["hour"]
        farm = obs["farms"][player]
        private = obs["private"]
        seeds = private["seeds"]
        shed = private["shed"]
        money = farm["money"]

        plan = _tile_plan(farm["unlocked_quadrants"], max_tiles, crop_mix)
        plan_by_pos = {(x, y): crop for x, y, crop in plan}

        market = []

        # --- Selling ---
        if sell == "dump":
            for crop in crops_in_mix:
                q = shed.get(crop, 0)
                if q > 0:
                    market.append(["SELL", crop, q])
        else:
            _, batch_n = sell
            for crop in crops_in_mix:
                q = shed.get(crop, 0)
                if q >= batch_n:
                    market.append(["SELL", crop, q])

        # --- Seed buying: top up to cover every empty plan tile ---
        empty_needed = {}
        for x, y, crop in plan:
            tile = farm["tiles"][y][x]
            if tile is None:
                empty_needed[crop] = empty_needed.get(crop, 0) + 1
        for crop, need in empty_needed.items():
            have = seeds.get(crop, 0)
            if need > have:
                market.append(["BUY_SEED", crop, need - have])

        # --- Land expansion (checked once, at the start of each day) ---
        if hour == 0:
            n_extra = len(farm["unlocked_quadrants"]) - 1
            land_costs = [1000, 2000, 4000]
            if land == "asap" and n_extra < 3 and money >= land_costs[n_extra] + 200:
                market.append(["BUY_LAND"])
            elif isinstance(land, list) and day in land and n_extra < 3:
                market.append(["BUY_LAND"])

        # --- Hiring: queue up to `hire` HIRE orders (fib-cost, cheap to expensive) ---
        if hour == 0 and hire >= 1 and money >= 50:
            for _ in range(hire):
                market.append(["HIRE"])

        # --- Fertilizer purchase (bonus policy only) ---
        fx, fy = farm["farmer"]
        main_inv = private["inventories"][0] if private["inventories"] else {}
        if fertilize == "bonus" and hour == 0:
            # Buy tomorrow's fertilizer today (BUY_PRODUCT lands directly in the
            # shed, but only after this step's farmer action is already decided,
            # so today's PICKUP can only draw on stock bought on a prior day).
            # Only buy the deficit beyond existing stock -- if FERTILIZE demand
            # ever goes unconsumed (e.g. a tile gets harvested before it's
            # reached), stock must stop growing instead of re-buying forever.
            demand_tomorrow = _fertilizer_demand(farm, plan, day + 1)
            stock = shed.get("FERTILIZER", 0) + main_inv.get("FERTILIZER", 0)
            if demand_tomorrow > stock:
                market.append(["BUY_PRODUCT", "FERTILIZER", demand_tomorrow - stock])
            # Pick up today's fertilizer, bought yesterday, at the morning spawn
            # (the farmer always starts the day shed-adjacent).
            demand_today = _fertilizer_demand(farm, plan, day)
            if demand_today > 0 and shed.get("FERTILIZER", 0) > 0:
                farmer_op = ["PICKUP", "FERTILIZER", min(demand_today, shed.get("FERTILIZER", 0))]
                return {"farmer": farmer_op, "hands": [], "market": market[:10]}

        # --- Build the set of tiles needing farmer/hand attention ---
        needing = []
        for x, y, crop in plan:
            tile = farm["tiles"][y][x]
            if _needs_action(tile, crop, day, harvest_at, fertilize):
                needing.append((x, y))

        def act_for_unit(ux, uy, is_farmer):
            pos = (ux, uy)
            if pos in needing and pos in plan_by_pos:
                crop = plan_by_pos[pos]
                tile = farm["tiles"][uy][ux]
                # Only the farmer ever carries fertilizer (see PICKUP above);
                # hands can't FERTILIZE, it would silently no-op in the real engine.
                have_fert = is_farmer and main_inv.get("FERTILIZER", 0) > 0
                act = _tile_action(tile, crop, day, harvest_at, fertilize, have_fert)
                if act == "PLANT":
                    return ["PLANT", crop]
                if act:
                    return [act]
                return ["PASS"]
            if not needing:
                return ["PASS"]
            tx, ty = min(needing, key=lambda t: abs(t[0] - ux) + abs(t[1] - uy))
            return [_step_toward(ux, uy, tx, ty)]

        farmer_action = act_for_unit(fx, fy, True)
        # Farmer claims its own tile so a hand doesn't also head for it.
        if (fx, fy) in needing:
            needing.remove((fx, fy))

        hands_actions = []
        for hx, hy in farm.get("hands", []):
            hands_actions.append(act_for_unit(hx, hy, False))
            if (hx, hy) in needing:
                needing.remove((hx, hy))

        return {"farmer": farmer_action, "hands": hands_actions, "market": market[:10]}

    return agent
