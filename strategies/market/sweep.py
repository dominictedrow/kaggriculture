"""Two-phase sweep runner for the market-tactics study.

Phase 1 (screen): every config in configs.CONFIGS vs "random" and "starter",
  n=8 episodes each, episode_steps=300. Cheap, used only to rank/prune.
Phase 2 (confirm): top N configs by combined screen score, re-run at
  n=30 episodes x 2 opponents x episode_steps=720 -- these are the numbers
  that go in FINDINGS.md.

Writes results_screen.csv and results_final.csv (both plain CSV, no deps).
Run from this directory: python sweep.py
"""

import csv
import os
import sys
import time

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(THIS_DIR, "..", ".."))
sys.path.insert(0, THIS_DIR)
sys.path.insert(0, ROOT)

from configs import CONFIGS          # noqa: E402
from agent import make_agent          # noqa: E402
from harness import run_matches       # noqa: E402

TOP_N_CONFIRM = 20
SCREEN_N = 8
SCREEN_STEPS = 300
CONFIRM_N = 30
CONFIRM_STEPS = 720

OPPONENTS = ["random", "starter"]


def _row(name, opponent, stats):
    return {
        "name": name, "opponent": opponent, "n": stats["n"],
        "mean": round(stats["mean"], 1), "median": round(stats["median"], 1),
        "min": round(stats["min"], 1), "max": round(stats["max"], 1),
        "stdev": round(stats["stdev"], 1),
    }


def write_csv(path, rows):
    if not rows:
        return
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)


def screen():
    print(f"Screening {len(CONFIGS)} configs x {len(OPPONENTS)} opponents "
          f"(n={SCREEN_N}, steps={SCREEN_STEPS})...", flush=True)
    rows = []
    scores = {}
    t0 = time.time()
    for i, cfg in enumerate(CONFIGS):
        means = []
        for opp in OPPONENTS:
            agent = make_agent(cfg)
            stats = run_matches(agent, opp, n_episodes=SCREEN_N, episode_steps=SCREEN_STEPS)
            rows.append(_row(cfg["name"], opp, stats))
            means.append(stats["mean"])
        scores[cfg["name"]] = sum(means) / len(means)
        elapsed = time.time() - t0
        print(f"  [{i+1}/{len(CONFIGS)}] {cfg['name']:35s} "
              f"combined_mean={scores[cfg['name']]:.0f}  ({elapsed:.0f}s elapsed)", flush=True)
    write_csv(os.path.join(THIS_DIR, "results_screen.csv"), rows)
    return scores


def confirm(scores):
    ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    top_names = {name for name, _ in ranked[:TOP_N_CONFIRM]}
    cfg_by_name = {c["name"]: c for c in CONFIGS}

    print(f"\nConfirming top {len(top_names)} configs "
          f"(n={CONFIRM_N} x {len(OPPONENTS)} opponents, steps={CONFIRM_STEPS})...", flush=True)
    rows = []
    combined = {}
    t0 = time.time()
    for i, name in enumerate(n for n, _ in ranked[:TOP_N_CONFIRM]):
        cfg = cfg_by_name[name]
        means = []
        for opp in OPPONENTS:
            agent = make_agent(cfg)
            stats = run_matches(agent, opp, n_episodes=CONFIRM_N, episode_steps=CONFIRM_STEPS)
            rows.append(_row(cfg["name"], opp, stats))
            means.append(stats["mean"])
        combined[name] = sum(means) / len(means)
        elapsed = time.time() - t0
        print(f"  [{i+1}/{len(top_names)}] {name:35s} combined_mean={combined[name]:.0f} "
              f"({elapsed:.0f}s elapsed)", flush=True)
    write_csv(os.path.join(THIS_DIR, "results_final.csv"), rows)

    print("\n=== FINAL RANKING (confirmed, n=30 x2 opponents, 720 steps) ===", flush=True)
    for name, score in sorted(combined.items(), key=lambda kv: kv[1], reverse=True):
        print(f"  {score:8.0f}  {name}", flush=True)
    return rows


if __name__ == "__main__":
    scores = screen()
    confirm(scores)
    print("\nDone. See results_screen.csv and results_final.csv", flush=True)
