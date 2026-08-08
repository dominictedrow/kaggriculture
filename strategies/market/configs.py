"""The full list of market-tactic configs under test. Each is a dict with
"name" plus "WHEAT" / "CARROT" resource-policy sub-dicts (consumed by
policy.build_market_orders) and optional wheat/fertilizer arbitrage add-ons.

Wheat (base $25) absorbs gluts (above_target 0.20, log) but panics on
scarcity (below_target 0.80, sqrt) -- dumping is cheap, holding for a
scarcity spike is the interesting alternative.
Carrot (base $35) is the mirror image: mild scarcity reaction (0.20, log)
but craters on oversupply (0.70, sqrt; P(I0+2T) = $1) -- dumping is
dangerous, gating/batching should matter a lot.
"""


def R(mode, **params):
    d = {"mode": mode}
    d.update(params)
    return d


WHEAT_DUMP = R("dump")
CARROT_DUMP = R("dump")

CONFIGS = []


def add(name, wheat, carrot, wheat_arb=None, fert_arb=None):
    CONFIGS.append({
        "name": name,
        "WHEAT": wheat,
        "CARROT": carrot,
        "wheat_arbitrage": wheat_arb,
        "fertilizer_arbitrage": fert_arb,
    })


# ---------------------------------------------------------------------------
# Phase A: wheat-axis sweep (carrot fixed at dump-immediate as control)
# ---------------------------------------------------------------------------
add("wheat_dump", WHEAT_DUMP, CARROT_DUMP)
for t in (5, 10, 20, 40, 80):
    add(f"wheat_threshold_{t}", R("threshold", threshold=t), CARROT_DUMP)
for mp in (10, 15, 20):
    add(f"wheat_pricegate_{mp}", R("price_gate", min_price=mp), CARROT_DUMP)
for cap in (5, 15, 30):
    add(f"wheat_capped_{cap}", R("capped", cap=cap), CARROT_DUMP)
add("wheat_shopscaled_5_2", R("shop_scaled_cap", base_cap=5, per_shop_bonus=2), CARROT_DUMP)

# ---------------------------------------------------------------------------
# Phase B: carrot-axis sweep (wheat fixed at dump-immediate as control)
# ---------------------------------------------------------------------------
for t in (3, 5, 10, 20, 40):
    add(f"carrot_threshold_{t}", WHEAT_DUMP, R("threshold", threshold=t))
for mp in (15, 20, 25, 30, 33):
    add(f"carrot_pricegate_{mp}", WHEAT_DUMP, R("price_gate", min_price=mp))
for cap in (1, 2, 5, 10):
    add(f"carrot_capped_{cap}", WHEAT_DUMP, R("capped", cap=cap))
for k in (2, 4, 7):
    add(f"carrot_dayspread_{k}", WHEAT_DUMP, R("day_spread", spread_k=k))
for base_cap, bonus in ((3, 1), (5, 2)):
    add(f"carrot_shopscaled_{base_cap}_{bonus}", WHEAT_DUMP,
        R("shop_scaled_cap", base_cap=base_cap, per_shop_bonus=bonus))
for t, mp in ((5, 20), (10, 25), (10, 20)):
    add(f"carrot_threshprice_{t}_{mp}", WHEAT_DUMP,
        R("threshold_and_price", threshold=t, min_price=mp))
add("carrot_gatehours_4", WHEAT_DUMP, R("gate_hours", interval=4))
add("carrot_hoard", WHEAT_DUMP, R("hoard"))

# ---------------------------------------------------------------------------
# Phase C: cross combos (a handful of wheat tactics x a handful of carrot
# tactics), since production is shared, only the sell layer differs.
# ---------------------------------------------------------------------------
WHEAT_PICKS = {
    "dump": WHEAT_DUMP,
    "threshold20": R("threshold", threshold=20),
    "capped15": R("capped", cap=15),
}
CARROT_PICKS = {
    "dump": CARROT_DUMP,
    "threshold10": R("threshold", threshold=10),
    "pricegate25": R("price_gate", min_price=25),
    "pricegate30": R("price_gate", min_price=30),
    "capped5": R("capped", cap=5),
    "dayspread4": R("day_spread", spread_k=4),
    "shopscaled_3_1": R("shop_scaled_cap", base_cap=3, per_shop_bonus=1),
    "threshprice_10_25": R("threshold_and_price", threshold=10, min_price=25),
}
for wname, wcfg in WHEAT_PICKS.items():
    for cname, ccfg in CARROT_PICKS.items():
        add(f"combo_{wname}_x_{cname}", wcfg, ccfg)

# ---------------------------------------------------------------------------
# Phase D: arbitrage add-ons on top of a reasonable default combo
# (wheat=dump since it absorbs gluts fine; carrot=price_gate25 conservative)
# ---------------------------------------------------------------------------
DEFAULT_WHEAT = WHEAT_DUMP
DEFAULT_CARROT = R("price_gate", min_price=25)

add("arb_wheat_only", DEFAULT_WHEAT, DEFAULT_CARROT,
    wheat_arb={"enabled": True, "buy_max": 20, "sell_min": 30, "budget_frac": 0.1, "max_buy": 5})
add("arb_fert_only", DEFAULT_WHEAT, DEFAULT_CARROT,
    fert_arb={"enabled": True, "buy_max": 70, "sell_min": 110, "budget_frac": 0.1, "max_buy": 5})
add("arb_both", DEFAULT_WHEAT, DEFAULT_CARROT,
    wheat_arb={"enabled": True, "buy_max": 20, "sell_min": 30, "budget_frac": 0.1, "max_buy": 5},
    fert_arb={"enabled": True, "buy_max": 70, "sell_min": 110, "budget_frac": 0.1, "max_buy": 5})
add("arb_wheat_aggressive", DEFAULT_WHEAT, DEFAULT_CARROT,
    wheat_arb={"enabled": True, "buy_max": 22, "sell_min": 25, "budget_frac": 0.25, "max_buy": 15})

print(f"Total configs: {len(CONFIGS)}")
