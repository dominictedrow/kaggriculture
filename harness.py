"""Shared simulation harness for testing Kaggriculture strategies.

run_matches() is the one entry point every strategy agent (in strategies/*/)
should use to score itself against a baseline opponent.
"""

import statistics

from kaggle_environments import make


def _final_money(env, player_idx):
    final_step = env.steps[-1]
    return final_step[player_idx].observation["farms"][player_idx]["money"]


def run_matches(agent, opponent, n_episodes, episode_steps=720):
    """Run n_episodes of agent vs opponent, split evenly across both player
    orders, and return stats on the agent's own final money (not win/loss).
    """
    moneys = []
    for i in range(n_episodes):
        agent_idx = i % 2  # alternate so ~half are P0, ~half P1
        agents = [agent, opponent] if agent_idx == 0 else [opponent, agent]
        env = make("kaggriculture", configuration={"episodeSteps": episode_steps}, debug=False)
        env.run(agents)
        moneys.append(_final_money(env, agent_idx))

    return {
        "n": len(moneys),
        "mean": statistics.mean(moneys),
        "median": statistics.median(moneys),
        "min": min(moneys),
        "max": max(moneys),
        "stdev": statistics.stdev(moneys) if len(moneys) > 1 else 0.0,
    }


def _demo():
    stats = run_matches("pass", "random", n_episodes=4, episode_steps=50)
    assert stats["n"] == 4
    assert stats["min"] <= stats["mean"] <= stats["max"]
    assert stats["min"] <= stats["median"] <= stats["max"]
    assert stats["mean"] >= 0
    print("harness self-check OK:", stats)


if __name__ == "__main__":
    _demo()
