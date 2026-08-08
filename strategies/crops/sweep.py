"""Runner: screen all configs cheaply, pick survivors, confirm at full scale.

Usage:
  python sweep.py phase1_screen
  python sweep.py phase2_screen
  python sweep.py confirm
"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))  # project root, for harness.py
sys.path.insert(0, str(Path(__file__).resolve().parent))  # this dir, for engine.py

from engine import make_agent
from harness import run_matches
import configs as cfgmod

RESULTS_DIR = Path(__file__).resolve().parent / "results"
RESULTS_DIR.mkdir(exist_ok=True)

OPPONENTS = ["random", "starter"]


def screen(config_dict, n_episodes=6, episode_steps=300, out_file="phase1_screen.json"):
    out_path = RESULTS_DIR / out_file
    results = {}
    if out_path.exists():
        results = json.loads(out_path.read_text())

    total = len(config_dict)
    for i, (name, cfg) in enumerate(config_dict.items()):
        if name in results:
            continue
        agent = make_agent(cfg)
        row = {"config": cfg_to_jsonable(cfg)}
        t0 = time.time()
        for opp in OPPONENTS:
            stats = run_matches(agent, opp, n_episodes=n_episodes, episode_steps=episode_steps)
            row[opp] = stats
        row["combined_mean"] = (row["random"]["mean"] + row["starter"]["mean"]) / 2
        row["elapsed"] = time.time() - t0
        results[name] = row
        out_path.write_text(json.dumps(results, indent=2))
        print(f"[{i+1}/{total}] {name}: combined_mean={row['combined_mean']:.0f} "
              f"(random={row['random']['mean']:.0f}, starter={row['starter']['mean']:.0f}) "
              f"[{row['elapsed']:.1f}s]", flush=True)
    return results


def cfg_to_jsonable(cfg):
    c = dict(cfg)
    c["crop_mix"] = [list(t) for t in c["crop_mix"]]
    return c


def cfg_from_jsonable(c):
    cfg = dict(c)
    cfg["crop_mix"] = [tuple(t) for t in cfg["crop_mix"]]
    if isinstance(cfg.get("sell"), list):
        cfg["sell"] = tuple(cfg["sell"])
    return cfg


def run_phase1():
    configs = cfgmod.phase1_configs()
    print(f"Phase 1: {len(configs)} configs")
    screen(configs, n_episodes=6, episode_steps=300, out_file="phase1_screen.json")


def top_n_from(out_file, n):
    path = RESULTS_DIR / out_file
    results = json.loads(path.read_text())
    ranked = sorted(results.items(), key=lambda kv: kv[1]["combined_mean"], reverse=True)
    return ranked[:n]


def run_phase2():
    top = top_n_from("phase1_screen.json", 10)
    survivors = []
    for name, row in top:
        cfg = cfg_from_jsonable(row["config"])
        mix_name = name.split("_mt")[0]
        survivors.append((mix_name, cfg["crop_mix"], cfg["max_tiles"]))
    configs = cfgmod.phase2_configs(survivors)
    print(f"Phase 2: {len(configs)} configs (from {len(survivors)} phase-1 survivors)")
    screen(configs, n_episodes=6, episode_steps=300, out_file="phase2_screen.json")


def run_confirm(n_top=20):
    p1 = json.loads((RESULTS_DIR / "phase1_screen.json").read_text())
    p2 = json.loads((RESULTS_DIR / "phase2_screen.json").read_text())
    all_results = {**p1, **p2}
    ranked = sorted(all_results.items(), key=lambda kv: kv[1]["combined_mean"], reverse=True)
    top = ranked[:n_top]
    configs = {name: cfg_from_jsonable(row["config"]) for name, row in top}
    print(f"Confirming top {len(configs)} configs at n=30 x 2 opponents x 720 steps")
    screen(configs, n_episodes=30, episode_steps=720, out_file="confirm.json")


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "phase1_screen"
    if mode == "phase1_screen":
        run_phase1()
    elif mode == "phase2_screen":
        run_phase2()
    elif mode == "confirm":
        run_confirm()
    else:
        print("unknown mode", mode)
