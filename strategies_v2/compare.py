"""Run every strategies_v2 strategy against the same baselines and print a
comparison table -- this is the "determine strategy superiority" entry point.
Each strategy also runs standalone (`python strategies_v2/ring.py`, etc.) for
one-off checks; this script is just the head-to-head runner.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from harness import run_matches
import checker
import headstart
import ring
import solid
import x_layout

STRATEGIES = {
    "ring": ring.agent,
    "solid": solid.agent,
    "checker": checker.agent,
    "x_layout": x_layout.agent,
    "headstart": headstart.agent,
}


def main(n_episodes=20, episode_steps=720, opponents=("random", "starter")):
    results = {}
    for name, agent in STRATEGIES.items():
        results[name] = {}
        for opp in opponents:
            stats = run_matches(agent, opp, n_episodes=n_episodes, episode_steps=episode_steps)
            results[name][opp] = stats
            print(f"{name:10s} vs {opp:8s}  mean={stats['mean']:.0f}  median={stats['median']:.0f}  "
                  f"min={stats['min']:.0f}  max={stats['max']:.0f}  stdev={stats['stdev']:.0f}")

    out_path = Path(__file__).resolve().parent / "results" / "compare.json"
    out_path.parent.mkdir(exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2)
    print("\nwritten to", out_path)
    return results


if __name__ == "__main__":
    main()
