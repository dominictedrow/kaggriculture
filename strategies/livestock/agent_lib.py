"""Parameterized livestock-strategy agent factory for Kaggriculture.

make_agent(**params) returns a pure function obs -> action_dict. The agent is
stateless (recomputes its plan from `obs` every call) so the same closure can
be reused safely across many episodes in run_matches without leaking state.

Core mechanic exploited here (see kaggriculture.py _daily_refresh_animals):
scheduled base production (+1 per interval) happens whether or not the animal
was fed *that specific day* -- only the banked CARE bonus requires same-day
feed. Feeding is only mandatory often enough to avoid 2 consecutive unfed
days (which causes an unrecoverable escape). That's what feed_mode="alternate"
exploits.
"""

ANIMALS_INFO = {
    "GOOSE": {"cost": 300, "structure": "COOP", "first_yield_day": 4, "interval": 1, "product": "EGG"},
    "COW":   {"cost": 400, "structure": "PASTURE", "first_yield_day": 8, "interval": 2, "product": "MILK"},
    "SHEEP": {"cost": 500, "structure": "PASTURE", "first_yield_day": 6, "interval": 3, "product": "WOOL"},
}

SHED_ADJACENT = {(4, 4), (5, 4), (4, 5), (5, 5)}

# Sweep order within the NW quadrant (always unlocked), starting at the
# farmer's spawn tile (4,4), which is also shed-adjacent.
_POSITIONS = [(x, y) for y in range(4, -1, -1) for x in range(4, -1, -1)]


def _is_shed_adjacent(pos):
    return pos in SHED_ADJACENT


def _step_toward(pos, target):
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


def make_agent(
    animal_plan,            # list[(animal_type, count)]
    feed_mode="daily",      # "daily" | "alternate"
    care_mode="always",     # "always" | "never"
    collect_fert=True,      # collect + sell fertilizer daily
    start_day=0,            # day to begin buying/building
    num_hands=0,            # extra hired hands per day (0-3)
    max_buy_per_day=None,   # cap on new animals bought per day (None = unlimited)
    buy_wheat_slack=0,      # extra wheat units to buy beyond exact daily need
):
    type_sequence = []
    for t, c in animal_plan:
        type_sequence += [t] * c
    total_n = len(type_sequence)
    positions = _POSITIONS[:total_n]
    n_units = 1 + num_hands

    # Split positions into contiguous chunks, one per unit (farmer first).
    chunk = max(1, -(-total_n // n_units))  # ceil div
    assignments = []
    for u in range(n_units):
        idxs = list(range(u * chunk, min(total_n, (u + 1) * chunk)))
        assignments.append(idxs)

    def _should_feed(tile):
        if feed_mode == "alternate":
            return tile["consecutive_unfed"] >= 1
        return True

    def _tile_at(tiles, idx):
        x, y = positions[idx]
        return tiles[y][x]

    def _unit_action(pos, inv, tiles, shed, idxs, day, bought_today_left):
        ux, uy = pos
        # 1. Act on current tile if it's one of ours.
        cur_idx = None
        for i in idxs:
            if positions[i] == (ux, uy):
                cur_idx = i
                break
        if cur_idx is not None:
            atype = type_sequence[cur_idx]
            structure = ANIMALS_INFO[atype]["structure"]
            tile = _tile_at(tiles, cur_idx)
            if tile is None:
                return ["BUILD_COOP" if structure == "COOP" else "BUILD_PASTURE"]
            if isinstance(tile, dict) and tile.get("kind") == structure and not tile.get("animal"):
                if inv.get(atype, 0) > 0:
                    return ["PLACE", atype]
                # fall through: no animal in hand yet
            elif isinstance(tile, dict) and tile.get("animal") == atype:
                if _should_feed(tile) and not tile["fed_today"]:
                    if inv.get("WHEAT", 0) > 0:
                        return ["FEED"]
                    # fall through: no wheat in hand
                elif tile["yield_units"] > 0:
                    return ["HARVEST"]
                elif collect_fert and tile["fertilizer_available"]:
                    return ["COLLECT_FERTILIZER"]
                elif care_mode == "always" and tile["fed_today"] and not tile["cared_today"]:
                    return ["CARE"]
                # else: nothing pending here, fall through to movement

        # 2. Pickup logic (only effective while standing on a shed-adjacent tile).
        if _is_shed_adjacent((ux, uy)):
            # Stock wheat for the WHOLE assigned chunk in one visit (not just
            # animals already placed/pending) so the unit never has to shuttle
            # back mid-route to restock -- that shuttling was starving animals.
            wheat_needed = len(idxs)
            if wheat_needed > inv.get("WHEAT", 0) and shed.get("WHEAT", 0) > 0:
                n = min(shed["WHEAT"], wheat_needed - inv.get("WHEAT", 0))
                if n > 0:
                    return ["PICKUP", "WHEAT", n]
            empty_needed = {}
            for i in idxs:
                atype = type_sequence[i]
                t = _tile_at(tiles, i)
                structure = ANIMALS_INFO[atype]["structure"]
                if isinstance(t, dict) and t.get("kind") == structure and not t.get("animal"):
                    empty_needed[atype] = empty_needed.get(atype, 0) + 1
            for atype, cnt in empty_needed.items():
                have = inv.get(atype, 0)
                need = cnt - have
                avail = shed.get(atype, 0)
                if need > 0 and avail > 0:
                    return ["PICKUP", atype, min(need, avail)]

        # 3. If some assigned position needs wheat/an animal we're not carrying
        # (and the shed likely has it, or a BUY order may land it), head back
        # to the nearest shed-adjacent tile rather than idling -- without this,
        # a unit that already left the shed for the day has no way back once
        # an empty structure needs an animal it isn't holding.
        if not _is_shed_adjacent((ux, uy)):
            unfed_remaining = 0
            missing_animal = False
            for i in idxs:
                atype = type_sequence[i]
                t = _tile_at(tiles, i)
                if isinstance(t, dict) and t.get("animal") == atype:
                    if _should_feed(t) and not t["fed_today"]:
                        unfed_remaining += 1
                elif isinstance(t, dict) and t.get("kind") == ANIMALS_INFO[atype]["structure"] and not t.get("animal"):
                    if inv.get(atype, 0) == 0:
                        missing_animal = True
            if unfed_remaining > inv.get("WHEAT", 0) or missing_animal:
                target = min(SHED_ADJACENT, key=lambda p: abs(p[0] - ux) + abs(p[1] - uy))
                step = _step_toward((ux, uy), target)
                if step:
                    return [step]

        # 4. Move toward the nearest assigned position that has an actionable need.
        for i in idxs:
            atype = type_sequence[i]
            t = _tile_at(tiles, i)
            needs = False
            if t is None:
                needs = True
            elif isinstance(t, dict) and t.get("kind") == ANIMALS_INFO[atype]["structure"] and not t.get("animal"):
                needs = inv.get(atype, 0) > 0
            elif isinstance(t, dict) and t.get("animal") == atype:
                if _should_feed(t) and not t["fed_today"] and inv.get("WHEAT", 0) > 0:
                    needs = True
                elif t["yield_units"] > 0:
                    needs = True
                elif collect_fert and t["fertilizer_available"]:
                    needs = True
                elif care_mode == "always" and t["fed_today"] and not t["cared_today"]:
                    needs = True
            if needs:
                step = _step_toward((ux, uy), positions[i])
                if step:
                    return [step]
        return ["PASS"]

    def agent(obs):
        player = obs["player"]
        me = obs["farms"][player]
        private = obs["private"]
        day = obs["day"]
        hour = obs["hour"]
        tiles = me["tiles"]
        shed = private.get("shed", {})
        money = me["money"]
        inventories = private.get("inventories", [{}])

        market = []

        # Sell everything except WHEAT (kept as feed stock).
        for item, n in list(shed.items()):
            if n > 0 and item != "WHEAT":
                market.append(["SELL", item, n])

        if day >= start_day:
            # Hire hands once at the start of the day.
            if hour == 0 and num_hands > 0:
                for _ in range(num_hands):
                    market.append(["HIRE"])

            # Buy animals still missing (placed + carried + in shed all count as "have").
            needed_counts = {}
            for i, atype in enumerate(type_sequence):
                x, y = positions[i]
                t = tiles[y][x]
                if not (isinstance(t, dict) and t.get("animal") == atype):
                    needed_counts[atype] = needed_counts.get(atype, 0) + 1
            for atype, need in needed_counts.items():
                have = shed.get(atype, 0)
                for inv in inventories:
                    have += inv.get(atype, 0)
                to_buy = max(0, need - have)
                if max_buy_per_day is not None:
                    to_buy = min(to_buy, max_buy_per_day)
                cost_each = ANIMALS_INFO[atype]["cost"]
                afford = int(money // cost_each) if cost_each > 0 else 0
                n_buy = min(to_buy, afford)
                if n_buy > 0:
                    market.append(["BUY_ANIMAL", atype, n_buy])
                    money -= n_buy * cost_each

            # Buy wheat for today's feeding across the whole farm. Target the
            # full roster size (not just currently-placed-and-pending animals)
            # so the shed always has enough for a single-visit PICKUP per unit.
            wheat_needed_total = total_n
            wheat_have = shed.get("WHEAT", 0)
            for inv in inventories:
                wheat_have += inv.get("WHEAT", 0)
            deficit = wheat_needed_total + buy_wheat_slack - wheat_have
            if deficit > 0 and money > 0:
                market.append(["BUY_PRODUCT", "WHEAT", deficit])

        farmer_action = ["PASS"]
        hands_actions = [["PASS"] for _ in range(len(me.get("hands", [])))]

        if day >= start_day:
            fx, fy = me["farmer"]
            farmer_inv = inventories[0] if inventories else {}
            farmer_action = _unit_action((fx, fy), farmer_inv, tiles, shed, assignments[0], day, None)

            hands_pos = me.get("hands", [])
            new_hands_actions = []
            for h_idx, hpos in enumerate(hands_pos):
                unit_num = h_idx + 1
                idxs = assignments[unit_num] if unit_num < len(assignments) else []
                if not idxs:
                    new_hands_actions.append(["PASS"])
                    continue
                hinv = inventories[unit_num] if unit_num < len(inventories) else {}
                new_hands_actions.append(_unit_action(tuple(hpos), hinv, tiles, shed, idxs, day, None))
            hands_actions = new_hands_actions

        return {"farmer": farmer_action, "hands": hands_actions, "market": market}

    return agent
