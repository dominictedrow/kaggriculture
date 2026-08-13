"""Submitted agent's strategy follower: combined livestock + melon build.

Plain top-level agent(obs) function -- no factory/closure -- so it reads as
a flat, directly-editable action layout and stays picklable for
harness.run_matches()'s ProcessPoolExecutor.

v2: generalized the crew-assignment layer (was hardcoded to exactly 2
livestock hands + 1 melon hand) so ANIMAL_MIX and hand counts can scale --
needed to chase a higher money target than the original 6-animal/19-melon-
tile build could reach. Sizing rationale (see RULES.md's Price Function
table): each glut-prone product's price floors once cumulative season sales
pass roughly its `T` throughput constant. At this build's yield rates,
wool's T=105 and milk's T=122 support far more animals before crashing than
melon's T=300 supports tiles (melon's higher yield/tile/day burns through
its bigger T just as fast) -- so the scale-up lever is more livestock, not
more melon. NE land ($1k) is bought to give melon room now that a bigger
herd claims more of NW.

AB-tested via test_gen.py (see ab_rounds/round4-15*.json) across two passes:

Pass 1 (round4-7): scaling the herd past ~14 animals backfired at first
(round5's 18/21-animal configs crashed to $16k-69k -- ongoing daily wheat
OPEX outpaces revenue before the bigger roster pays off), and a single melon
hand became the bottleneck once the herd grew (round6: 2 melon hands beats
1). round7 (n=30) confirmed winner: 82,793 combined mean, beating the
original 6-animal/1-melon-hand build's 60,970 by +36%. Also fixed a real bug
found along the way: wheat purchases were gated on `money > 0`, so a big
enough one-time spend (animals + land) could zero the cash out and then
*permanently* block wheat buying, starving the whole herd to death (2 unfed
days = animal escapes, unrecoverable) with no way to recover -- wheat is now
funded first, before animals/land get whatever's left.

Pass 2 (round8-15, chasing a 95k target): added nearest-need routing (was
walking to the first needy tile in index order, not the closest one) and an
urgency tier (an unfed animal/unwatered-young-melon is one missed day from
irrecoverable loss, so it now always outranks routine harvest/care) -- a real
correctness fix, but its measured effect was within noise once confirmed at
scale (n=30), not a big lever on its own. Land-purchase timing/priority and
animal-purchase-pacing knobs were added and swept; none beat the original
"greedy, animals first" defaults. Re-sweeping herd size found a real (if
narrow) sweet spot at 17 animals (11 COW + 6 SHEEP, 6 hands) -- 18+ reliably
regressed again, this time because a bigger roster's upfront cost crowds out
land purchase entirely (confirmed: `unlocked_quadrants` stayed `['NW']` the
whole game in the 18-animal case). The one genuine additional win was sell
price gating (`SELL_MIN_PRICE_FRAC`): CONSOLIDATED_FINDINGS flagged this as
"worth testing" for glut-fragile goods and phase 1 never tried it at this
production volume -- holding melon/milk/wool instead of dumping them while
the price is beaten down below 40% of base beat dump-immediate by a
consistent, confirmed margin. n=50 confirm: 86,253 combined mean.

Pass 3 (round16-21, crop diversification, still chasing 95k): generalized
melon's tile-action into `_crop_action(crop, max_yield_day, ...)`, shared by
MELON/WHEAT/CARROT, and generalized the crew-assignment into `_CREW_PLAN` (a
flat hand-slot -> (job, tile-group) list) so any number of job types can
share the hire pool. Also found and fixed a real crash along the way:
standing on a still-locked tile (a plain "LOCKED" string, not a dict or None)
called `.get()` on it and raised AttributeError -- latent in melon's tile
pool too (it also reaches into NE) but never triggered until wheat's spare-
tile pool reached deeper into still-locked territory. Also found that HIRE
competes with every BUY_* for the same 10-orders/turn cap, and with hand
counts approaching double digits HIRE alone could fill it, silently dropping
every buy (and every sell) that turn -- fixed by giving each purchase
category its own hour instead of bundling them all into hour 0 (only HIRE
actually needs hour 0, since hands are hired once for the whole day).

The crop economics looked compelling on paper -- wheat barely reacts to glut
(T=400, above_target=0.2) so growing our own feed instead of buying it
looked like near-free money, and carrot's price pool is entirely separate
from melon's -- but none of it held up under confirmation. Small-n screens
(n=15) showed wheat self-farming beating baseline by several thousand
(round16/17), but every n=30+ confirm (round18/19/20) put wheat-alone,
carrot-alone, and the no-crops baseline within noise of each other
(81k-86k), and wheat+carrot combined together was outright worse and
unstable (round16: bimodal, stdev ~43k, sometimes $0). The marginal hand's
hire cost plus the crop-tending overhead apparently roughly cancels out
whatever wheat/carrot revenue they add at this scale -- this game's
per-episode variance (stdev commonly $7k-45k depending on config) is large
enough that a lever has to be worth several thousand dollars before n=30-50
can tell it apart from noise, and neither crop cleared that bar. Final
confirmed number, unchanged from pass 2: 86,810 combined mean (n=40,
consistent with pass 2's 86,253 at n=50) -- didn't reach the 95k target; see
the chat writeup for what a genuinely structural change (SW/SE land, a
different crew architecture) would need to try next.
"""

# ---- Constants (the "easy to change" knobs) --------------------------------

ANIMAL_MIX = {"COW": 11, "SHEEP": 6}  # AB-tested winner (round15_final.json, n=50): 86,253 combined mean
ANIMAL_COST = {"COW": 400, "SHEEP": 500}
LIVESTOCK_HANDS = 6                    # + farmer = 7 units / 17 animals, ~2.4 tiles/unit
MELON_HANDS = 2                        # splitting the 19 melon tiles across 2 units beat 1 hand at this scale --
                                        # a single melon hand couldn't service the tiles fast enough (round5/6/7);
                                        # a 3rd hand was tried and reliably broke the economics (round11/13) -- not used
MAX_MELON_TILES = 19                   # melon's own T=300 / 0.55 yield-per-tile-day / 30 days ~= 18 tiles -- keep near that;
                                        # expanding to 26 tiles under NE tested statistically tied, not worth the complexity (round14)
MELON_YIELD_DAY = 10                   # melon: first_yield_day == max_yield_day == 10 (RULES.md Object Types)
BUY_NE_LAND = True                     # NW alone (25 tiles) can't hold 17 livestock + 19 melon; NE ($1k) covers it
LAND_MIN_DAY = 0                       # earliest day to attempt BUY_LAND -- 0 = as soon as affordable (swept, best default)
MAX_ANIMAL_BUY_PER_DAY = None          # None = uncapped -- buy every affordable animal every day (swept, best default)
SELL_MIN_PRICE_FRAC = 0.4              # hold melon/milk/wool instead of dumping while price is below 40% of base --
                                        # confirmed win over dump-immediate (round12/14/15) once production volume is high enough to move the price
_BASE_PRICE = {"MELON": 250, "MILK": 160, "WOOL": 200, "CARROT": 35}  # RULES.md Object Types table -- for the sell-gate check above

# ---- Crop diversification knobs --------------------------------------------
# Wheat's price barely reacts to glut (T=400, above_target=0.2 -- RULES.md
# Price Function table) unlike melon/carrot/livestock products, so growing
# our own feed instead of buying it is close to free money once tiles exist
# for it; carrot is a genuinely separate revenue pool (its own price/T) that
# doesn't compete with melon's for the same throughput ceiling.
WHEAT_TILES = 0                        # self-grow feed wheat (and sell any surplus) instead of buying all of it; 0 = off
WHEAT_HANDS = 0
CARROT_TILES = 0                       # secondary cash crop, separate price pool from melon; 0 = off
CARROT_HANDS = 0
CROP_MAX_YIELD_DAY = {"MELON": MELON_YIELD_DAY, "WHEAT": 4, "CARROT": 3}  # RULES.md Object Types table

ANIMAL_STRUCTURE = "PASTURE"
SHED_ADJACENT = {(4, 4), (5, 4), (4, 5), (5, 5)}

# NW quadrant, backward scan from the farmer's shed-adjacent spawn (4, 4) --
# same order as the proven livestock finding's tile pick.
_NW_BACKWARD = [(x, y) for y in range(4, -1, -1) for x in range(4, -1, -1)]


def _livestock_type_sequence():
    seq = []
    for animal, count in ANIMAL_MIX.items():
        seq += [animal] * count
    return seq


LIVESTOCK_TYPES = _livestock_type_sequence()
LIVESTOCK_POSITIONS = _NW_BACKWARD[: len(LIVESTOCK_TYPES)]

# Crop pool: NW forward scan minus livestock's tiles, then NE forward scan
# (only reachable once BUY_NE_LAND unlocks it -- locked tiles are passable
# but PLANT no-ops on them, so listing them early is harmless, not incorrect).
# Melon claims the first MAX_MELON_TILES; wheat and carrot split whatever's
# left, in that order.
_claimed = set(LIVESTOCK_POSITIONS)
_NW_FREE = [(x, y) for y in range(0, 5) for x in range(0, 5) if (x, y) not in _claimed]
_NE_FORWARD = [(x, y) for y in range(0, 5) for x in range(5, 10)]
_ALL_FREE = _NW_FREE + _NE_FORWARD
MELON_POSITIONS = _ALL_FREE[:MAX_MELON_TILES]
_SPARE = _ALL_FREE[MAX_MELON_TILES:]
WHEAT_POSITIONS = _SPARE[:WHEAT_TILES]
CARROT_POSITIONS = _SPARE[WHEAT_TILES:WHEAT_TILES + CARROT_TILES]


def _chunk_indices(n_items, n_groups):
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


# Crew split: farmer + LIVESTOCK_HANDS hands round-robin the livestock tiles
# in even chunks; MELON_HANDS/WHEAT_HANDS/CARROT_HANDS each round-robin their
# own crop's tiles. _CREW_PLAN flattens this into one job per hand-slot, in
# hire order, so the hands loop below just indexes into it -- adding a new
# job type only means appending another job-group list here.
LIVESTOCK_GROUPS = _chunk_indices(len(LIVESTOCK_POSITIONS), 1 + LIVESTOCK_HANDS)
MELON_GROUPS = _chunk_indices(len(MELON_POSITIONS), MELON_HANDS)
WHEAT_GROUPS = _chunk_indices(len(WHEAT_POSITIONS), WHEAT_HANDS)
CARROT_GROUPS = _chunk_indices(len(CARROT_POSITIONS), CARROT_HANDS)

_CREW_PLAN = (
    [("LIVESTOCK", g) for g in LIVESTOCK_GROUPS[1:]]  # group 0 is the farmer, handled separately
    + [("MELON", g) for g in MELON_GROUPS]
    + [("WHEAT", g) for g in WHEAT_GROUPS]
    + [("CARROT", g) for g in CARROT_GROUPS]
)
N_HIRES = len(_CREW_PLAN)


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


def _is_shed_adjacent(pos):
    return pos in SHED_ADJACENT


def _nearest_step(pos, positions):
    """Step toward the closest of `positions` (Manhattan), not just the
    first one found -- every wasted step here is an action turn not spent
    watering/feeding/harvesting.
    """
    if not positions:
        return None
    ux, uy = pos
    target = min(positions, key=lambda p: abs(p[0] - ux) + abs(p[1] - uy))
    return _step_toward(pos, target)


# ---- Livestock unit action (adapted from agent_lib.py::_unit_action, ------
# simplified since both COW and SHEEP use PASTURE -- no COOP branching) -----

def _livestock_action(pos, inv, tiles, shed, idxs):
    ux, uy = pos
    cur_idx = next((i for i in idxs if LIVESTOCK_POSITIONS[i] == (ux, uy)), None)
    if cur_idx is not None:
        atype = LIVESTOCK_TYPES[cur_idx]
        x, y = LIVESTOCK_POSITIONS[cur_idx]
        tile = tiles[y][x]
        if tile is None:
            return ["BUILD_PASTURE"]
        if tile.get("kind") == ANIMAL_STRUCTURE and not tile.get("animal"):
            if inv.get(atype, 0) > 0:
                return ["PLACE", atype]
        elif tile.get("animal") == atype:
            if not tile["fed_today"]:
                if inv.get("WHEAT", 0) > 0:
                    return ["FEED"]
            elif tile["yield_units"] > 0:
                return ["HARVEST"]
            elif tile["fertilizer_available"]:
                return ["COLLECT_FERTILIZER"]
            elif not tile["cared_today"]:
                return ["CARE"]

    if _is_shed_adjacent((ux, uy)):
        # Stock wheat for the WHOLE assigned chunk in one visit so the unit
        # never has to shuttle back mid-route to restock.
        wheat_needed = len(idxs)
        if wheat_needed > inv.get("WHEAT", 0) and shed.get("WHEAT", 0) > 0:
            n = min(shed["WHEAT"], wheat_needed - inv.get("WHEAT", 0))
            if n > 0:
                return ["PICKUP", "WHEAT", n]
        empty_needed = {}
        for i in idxs:
            atype = LIVESTOCK_TYPES[i]
            x, y = LIVESTOCK_POSITIONS[i]
            t = tiles[y][x]
            if isinstance(t, dict) and t.get("kind") == ANIMAL_STRUCTURE and not t.get("animal"):
                empty_needed[atype] = empty_needed.get(atype, 0) + 1
        for atype, cnt in empty_needed.items():
            need = cnt - inv.get(atype, 0)
            avail = shed.get(atype, 0)
            if need > 0 and avail > 0:
                return ["PICKUP", atype, min(need, avail)]

    if not _is_shed_adjacent((ux, uy)):
        unfed_remaining = 0
        missing_animal = False
        for i in idxs:
            atype = LIVESTOCK_TYPES[i]
            x, y = LIVESTOCK_POSITIONS[i]
            t = tiles[y][x]
            if isinstance(t, dict) and t.get("animal") == atype:
                if not t["fed_today"]:
                    unfed_remaining += 1
            elif isinstance(t, dict) and t.get("kind") == ANIMAL_STRUCTURE and not t.get("animal"):
                if inv.get(atype, 0) == 0:
                    missing_animal = True
        if unfed_remaining > inv.get("WHEAT", 0) or missing_animal:
            target = min(SHED_ADJACENT, key=lambda p: abs(p[0] - ux) + abs(p[1] - uy))
            step = _step_toward((ux, uy), target)
            if step:
                return [step]

    # Two priority tiers, nearest-first within each: an unfed animal is one
    # missed day from irrecoverable escape, so feeding always outranks
    # harvest/care/place -- but among several feed-needy tiles, still walk
    # to the closest one first, not just the first in index order.
    feed_needy = []
    other_needy = []
    for i in idxs:
        atype = LIVESTOCK_TYPES[i]
        x, y = LIVESTOCK_POSITIONS[i]
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
    step = _nearest_step((ux, uy), feed_needy) or _nearest_step((ux, uy), other_needy)
    if step:
        return [step]
    return ["PASS"]


# ---- One-time crop unit action (adapted from engine.py::_tile_action) -----
# Shared by MELON, WHEAT, and CARROT -- all three are the same "plant / dig
# weed / water until max_yield_day / harvest" one-time-crop mechanic, just
# with different max_yield_day and seed price. Ongoing crops (tomato,
# strawberry) would need a different function -- not used here.

def _crop_action(crop, max_yield_day, pos, day, tiles, idxs, positions):
    ux, uy = pos
    cur_idx = next((i for i in idxs if positions[i] == (ux, uy)), None)
    if cur_idx is not None:
        x, y = positions[cur_idx]
        tile = tiles[y][x]
        if tile is None:
            return ["PLANT", crop]
        # A crop tile pool can reach into NE before land is bought (locked
        # tiles are passable, so a unit can end up standing on one); "LOCKED"
        # is a plain string, not a dict, so it must be excluded here or the
        # .get() calls below raise AttributeError.
        if isinstance(tile, dict):
            if tile.get("kind") == "WEED":
                return ["DIG"]
            if tile.get("kind") == "PLANT":
                age = day - tile["planted_day"]
                if age >= max_yield_day and tile["yield_units"] > 0:
                    return ["HARVEST"]
                if not tile["watered_today"]:
                    return ["WATER"]

    # Watering an unripe plant outranks harvest/plant/dig -- two consecutive
    # unwatered days turns it into a weed (irrecoverable), same reasoning as
    # livestock's feed-first tier. Nearest-first within each tier.
    water_needy = []
    other_needy = []
    for i in idxs:
        x, y = positions[i]
        t = tiles[y][x]
        if t is None:
            other_needy.append((x, y))
        elif isinstance(t, dict) and t.get("kind") == "WEED":
            other_needy.append((x, y))
        elif isinstance(t, dict) and t.get("kind") == "PLANT":
            age = day - t["planted_day"]
            if age >= max_yield_day and t["yield_units"] > 0:
                other_needy.append((x, y))
            elif not t["watered_today"]:
                water_needy.append((x, y))
    step = _nearest_step((ux, uy), water_needy) or _nearest_step((ux, uy), other_needy)
    if step:
        return [step]
    return ["PASS"]


def _melon_action(pos, day, tiles, idxs):
    return _crop_action("MELON", MELON_YIELD_DAY, pos, day, tiles, idxs, MELON_POSITIONS)


def _wheat_crop_action(pos, day, tiles, idxs):
    return _crop_action("WHEAT", CROP_MAX_YIELD_DAY["WHEAT"], pos, day, tiles, idxs, WHEAT_POSITIONS)


def _carrot_action(pos, day, tiles, idxs):
    return _crop_action("CARROT", CROP_MAX_YIELD_DAY["CARROT"], pos, day, tiles, idxs, CARROT_POSITIONS)


# Kaggle's real submission loader (kaggle_environments/agent.py::get_last_callable)
# execs this file and picks the LAST top-level callable defined, not something
# named "agent" specifically -- so nothing may be defined below this function,
# or that (0-arg, non-observation-taking) callable silently becomes "the agent"
# instead, called with no args every turn.
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

    buy_orders = []
    sell_orders = []

    # Only HIRE truly needs hour 0 (hands are hired for the whole day, once).
    # Every other purchase type is spread across its own hour instead of all
    # piling into hour 0 -- maxMarketOrdersPerTurn (10) is a *per-turn* cap,
    # and with N_HIRES approaching double digits, HIRE alone can fill it,
    # silently dropping every other buy (and every sell) that day if they
    # all queued at hour 0 too. One purchase category per hour sidesteps the
    # cap entirely regardless of how many hands/crops are configured.
    prices = obs.get("market", {}).get("prices", {})

    for item, n in list(shed.items()):
        if n <= 0 or item == "WHEAT":
            continue
        base = _BASE_PRICE.get(item)
        cur = prices.get(item)
        # Hold instead of dumping while the price is depressed below the
        # gate -- but never past shedCapacity (100): losing product to
        # overflow is strictly worse than selling it cheap.
        if SELL_MIN_PRICE_FRAC > 0 and base and cur is not None and cur < SELL_MIN_PRICE_FRAC * base and n < 90:
            continue
        sell_orders.append(["SELL", item, n])

    if WHEAT_TILES > 0:
        # Wheat barely reacts to glut (RULES.md Price Function table), so
        # any surplus beyond a 2-day feed reserve is free money to sell,
        # not just a cost saved on feed.
        wheat_reserve = len(LIVESTOCK_TYPES) * 2
        wheat_surplus = shed.get("WHEAT", 0) - wheat_reserve
        if wheat_surplus > 0:
            sell_orders.append(["SELL", "WHEAT", wheat_surplus])

    if hour == 0:
        for _ in range(N_HIRES):
            buy_orders.append(["HIRE"])

    if hour == 1:
        # Wheat feed is funded before any other spend, at the live market
        # price -- an existing herd starving because some other purchase ate
        # the day's cash is an unrecoverable death spiral (2 unfed days =
        # animal escapes for good), so feeding what's alive always wins.
        # Self-grown wheat (if any) already lowered `wheat_have`, so this
        # naturally only tops up whatever the wheat plot didn't cover.
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
        # Buy missing COW/SHEEP up to ANIMAL_MIX, capped by affordability
        # and (if set) a per-day purchase cap.
        needed_counts = {}
        for i, atype in enumerate(LIVESTOCK_TYPES):
            x, y = LIVESTOCK_POSITIONS[i]
            t = tiles[y][x]
            if not (isinstance(t, dict) and t.get("animal") == atype):
                needed_counts[atype] = needed_counts.get(atype, 0) + 1
        remaining_cap = MAX_ANIMAL_BUY_PER_DAY if MAX_ANIMAL_BUY_PER_DAY is not None else sum(needed_counts.values())
        cash = money
        for atype, need in needed_counts.items():
            if remaining_cap <= 0:
                break
            have = shed.get(atype, 0)
            for inv in inventories:
                have += inv.get(atype, 0)
            to_buy = max(0, need - have)
            cost_each = ANIMAL_COST[atype]
            afford = int(cash // cost_each)
            n_buy = min(to_buy, afford, remaining_cap)
            if n_buy > 0:
                buy_orders.append(["BUY_ANIMAL", atype, n_buy])
                cash -= n_buy * cost_each
                remaining_cap -= n_buy

    if hour == 3 and BUY_NE_LAND and day >= LAND_MIN_DAY and "NE" not in me.get("unlocked_quadrants", ["NW"]) and money >= 1200:
        buy_orders.append(["BUY_LAND"])

    if hour == 4:
        empty_melon = sum(1 for x, y in MELON_POSITIONS if tiles[y][x] is None)
        have_seeds = seeds.get("MELON", 0)
        if empty_melon > have_seeds:
            buy_orders.append(["BUY_SEED", "MELON", empty_melon - have_seeds])

    if hour == 5 and WHEAT_TILES > 0:
        empty_wheat = sum(1 for x, y in WHEAT_POSITIONS if tiles[y][x] is None)
        have_seeds = seeds.get("WHEAT", 0)
        if empty_wheat > have_seeds:
            buy_orders.append(["BUY_SEED", "WHEAT", empty_wheat - have_seeds])

    if hour == 6 and CARROT_TILES > 0:
        empty_carrot = sum(1 for x, y in CARROT_POSITIONS if tiles[y][x] is None)
        have_seeds = seeds.get("CARROT", 0)
        if empty_carrot > have_seeds:
            buy_orders.append(["BUY_SEED", "CARROT", empty_carrot - have_seeds])

    market = buy_orders + sell_orders

    fx, fy = me["farmer"]
    farmer_inv = inventories[0] if inventories else {}
    farmer_idxs = LIVESTOCK_GROUPS[0] if LIVESTOCK_GROUPS else []
    farmer_action = _livestock_action((fx, fy), farmer_inv, tiles, shed, farmer_idxs) if farmer_idxs else ["PASS"]

    _DISPATCH = {
        "LIVESTOCK": lambda pos, inv, idxs: _livestock_action(pos, inv, tiles, shed, idxs),
        "MELON": lambda pos, inv, idxs: _melon_action(pos, day, tiles, idxs),
        "WHEAT": lambda pos, inv, idxs: _wheat_crop_action(pos, day, tiles, idxs),
        "CARROT": lambda pos, inv, idxs: _carrot_action(pos, day, tiles, idxs),
    }

    hands = me.get("hands", [])
    hands_actions = []
    for h_idx, hpos in enumerate(hands):
        hinv = inventories[h_idx + 1] if h_idx + 1 < len(inventories) else {}
        if h_idx < len(_CREW_PLAN):
            job, idxs = _CREW_PLAN[h_idx]
            hands_actions.append(_DISPATCH[job](tuple(hpos), hinv, idxs) if idxs else ["PASS"])
        else:
            hands_actions.append(["PASS"])

    return {"farmer": farmer_action, "hands": hands_actions, "market": market}
