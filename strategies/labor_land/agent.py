"""Builds an obs -> action callable from a (hire_policy, land_policy,
allocation) triple, running the fixed wheat-loop production task from
production.py underneath."""

from production import unit_actions_for_turn, market_orders
from policies import utilization

MAX_MARKET_ORDERS = 10


def make_agent(hire_policy, land_policy, allocation="stripe"):
    def agent(obs):
        player = obs["player"]
        farm = obs["farms"][player]
        private = obs["private"]
        day, hour = obs["day"], obs["hour"]
        board_size = len(farm["tiles"])
        n_units = 1 + len(farm["hands"])

        farmer_action, hand_actions = unit_actions_for_turn(farm, day, allocation)

        util = utilization(farm, board_size)
        nq = len(farm["unlocked_quadrants"])
        money = farm["money"]
        hires_today = farm["hires_today"]

        budget = MAX_MARKET_ORDERS
        market, budget = market_orders(farm, private, n_units, budget)

        want_land = nq < 4 and land_policy(day, hour, money, nq, util)
        reserve = 1 if want_land else 0

        desired_hires = hire_policy(day, hour, money, hires_today, nq, util)
        n_more = max(0, desired_hires - hires_today)
        n_more = min(n_more, max(0, budget - reserve))
        for _ in range(n_more):
            market.append(["HIRE"])
        budget -= n_more

        if want_land and budget > 0:
            market.append(["BUY_LAND"])

        return {"farmer": farmer_action, "hands": hand_actions, "market": market}

    return agent


def _demo():
    """ponytail: smallest runnable check that the whole plumbing produces
    valid, well-shaped actions across a few turns -- not a full game sim."""
    import policies as P

    agent = make_agent(P.hire_flat(2), P.land_buy_immediately(), "stripe")
    obs = {
        "player": 0,
        "day": 0,
        "hour": 0,
        "farms": [
            {
                "money": 3000.0,
                "tiles": [[None if 0 <= x < 5 and 0 <= y < 5 else "LOCKED" for x in range(10)] for y in range(10)],
                "farmer": [4, 4],
                "hands": [[3, 4]],
                "unlocked_quadrants": ["NW"],
                "hires_today": 0,
            },
            {"money": 3000.0, "tiles": [[None] * 10 for _ in range(10)], "farmer": [4, 4], "hands": [],
             "unlocked_quadrants": ["NW"], "hires_today": 0},
        ],
        "private": {"shed": {"WHEAT": 3}, "seeds": {"WHEAT": 0}, "inventories": [{}, {}]},
        "market": {"inventory": {}, "prices": {}},
        "town": {"unlocked_shops": []},
    }
    action = agent(obs)
    assert "farmer" in action and "hands" in action and "market" in action
    assert isinstance(action["farmer"], list) and len(action["farmer"]) >= 1
    assert isinstance(action["hands"], list) and len(action["hands"]) == 1
    assert any(o[0] == "SELL" and o[1] == "WHEAT" for o in action["market"])
    assert any(o[0] == "HIRE" for o in action["market"])
    assert any(o[0] == "BUY_LAND" for o in action["market"])
    print("agent self-check OK:", action)


if __name__ == "__main__":
    _demo()
