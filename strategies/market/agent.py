"""Combines the fixed production baseline with a pluggable market policy
into a single stateful agent callable, as expected by harness.run_matches.
"""

from production import BaselineFarmer
from policy import build_market_orders

MAX_ORDERS = 10


def make_agent(cfg):
    farmer = BaselineFarmer()

    def agent(obs):
        farmer_action, prod_orders = farmer.step(obs)
        player = obs["player"]
        shed = obs["private"]["shed"]
        prices = obs["market"]["prices"]
        money = obs["farms"][player]["money"]
        town = obs.get("town", {}) or {}
        num_shops = len(town.get("unlocked_shops", []))

        policy_orders = build_market_orders(
            cfg, shed=shed, prices=prices, day=obs["day"], hour=obs["hour"],
            money=money, num_shops=num_shops,
        )
        orders = (prod_orders + policy_orders)[:MAX_ORDERS]
        return {"farmer": farmer_action, "hands": [], "market": orders}

    return agent
