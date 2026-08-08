"""Pluggable market (sell/buy) tactics layered on top of production.py.

Every config is a plain dict (see configs.py) consumed by build_market_orders().
Each resource (WHEAT, CARROT) gets an independent sell "mode" with its own
params; wheat and fertilizer additionally support a cheap-buy arbitrage
add-on. Nothing here touches farming/production.
"""

BASE_PRICE = {"WHEAT": 25, "CARROT": 35, "FERTILIZER": 100}


def _sell_qty(mode, params, shed_qty, price, hour, num_shops):
    if shed_qty <= 0:
        return 0
    if mode == "dump":
        return shed_qty
    if mode == "threshold":
        return shed_qty if shed_qty >= params["threshold"] else 0
    if mode == "price_gate":
        return shed_qty if price >= params["min_price"] else 0
    if mode == "threshold_and_price":
        ok = shed_qty >= params["threshold"] and price >= params["min_price"]
        return shed_qty if ok else 0
    if mode == "capped":
        return min(shed_qty, params["cap"])
    if mode == "shop_scaled_cap":
        cap = params["base_cap"] + params["per_shop_bonus"] * num_shops
        return min(shed_qty, max(1, cap))
    if mode == "day_spread":
        if hour != 0:
            return 0
        return max(1, shed_qty // params["spread_k"])
    if mode == "gate_hours":
        return shed_qty if (hour % params["interval"]) == 0 else 0
    if mode == "hoard":
        return 0
    return shed_qty  # fallback: dump


def build_market_orders(cfg, shed, prices, day, hour, money, num_shops):
    orders = []

    for item in ("WHEAT", "CARROT"):
        rcfg = cfg.get(item)
        if rcfg is None:
            continue
        qty = _sell_qty(rcfg["mode"], rcfg, shed.get(item, 0), prices.get(item, 0), hour, num_shops)
        if qty > 0:
            orders.append(["SELL", item, qty])

    wa = cfg.get("wheat_arbitrage")
    if wa and wa.get("enabled"):
        price = prices.get("WHEAT", BASE_PRICE["WHEAT"])
        if price <= wa["buy_max"]:
            budget = money * wa.get("budget_frac", 0.1)
            max_buy = wa.get("max_buy", 5)
            qty = max(0, min(max_buy, int(budget // max(price, 1))))
            if qty > 0:
                orders.append(["BUY_PRODUCT", "WHEAT", qty])

    fa = cfg.get("fertilizer_arbitrage")
    if fa and fa.get("enabled"):
        price = prices.get("FERTILIZER", BASE_PRICE["FERTILIZER"])
        fert_shed = shed.get("FERTILIZER", 0)
        if price <= fa["buy_max"]:
            budget = money * fa.get("budget_frac", 0.1)
            max_buy = fa.get("max_buy", 5)
            qty = max(0, min(max_buy, int(budget // max(price, 1))))
            if qty > 0:
                orders.append(["BUY_PRODUCT", "FERTILIZER", qty])
        if fert_shed > 0 and price >= fa["sell_min"]:
            orders.append(["SELL", "FERTILIZER", fert_shed])

    return orders
