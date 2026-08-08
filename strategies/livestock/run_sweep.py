"""Two-phase sweep for livestock strategies: screen many configs cheaply,
then confirm the top survivors at full n=30 x 2 opponents x 720 steps.

Run from strategies/livestock/:
    python run_sweep.py screen1   # baseline animal-plan screen
    python run_sweep.py screen2   # variant screen (reads screen1 results)
    python run_sweep.py confirm   # full confirmation of top overall configs
"""
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from harness import run_matches
from agent_lib import make_agent

RESULTS_DIR = Path(__file__).resolve().parent / "results"
RESULTS_DIR.mkdir(exist_ok=True)

OPPONENTS = ["random", "starter"]

# ---------------------------------------------------------------- Phase 1: baseline animal-plan configs
BASELINE_PLANS = {
    "goose1":  [("GOOSE", 1)],
    "goose2":  [("GOOSE", 2)],
    "goose4":  [("GOOSE", 4)],
    "goose6":  [("GOOSE", 6)],
    "goose8":  [("GOOSE", 8)],
    "goose10": [("GOOSE", 10)],
    "cow1":  [("COW", 1)],
    "cow2":  [("COW", 2)],
    "cow4":  [("COW", 4)],
    "cow6":  [("COW", 6)],
    "sheep1":  [("SHEEP", 1)],
    "sheep2":  [("SHEEP", 2)],
    "sheep4":  [("SHEEP", 4)],
    "sheep6":  [("SHEEP", 6)],
    "mix_g2c2":     [("GOOSE", 2), ("COW", 2)],
    "mix_g2s2":     [("GOOSE", 2), ("SHEEP", 2)],
    "mix_c2s2":     [("COW", 2), ("SHEEP", 2)],
    "mix_g2c2s2":   [("GOOSE", 2), ("COW", 2), ("SHEEP", 2)],
    "mix_g4c2":     [("GOOSE", 4), ("COW", 2)],
    "mix_g4s2":     [("GOOSE", 4), ("SHEEP", 2)],
    "mix_c4s2":     [("COW", 4), ("SHEEP", 2)],
    "mix_g1c1s1":   [("GOOSE", 1), ("COW", 1), ("SHEEP", 1)],
    "mix_g3c3":     [("GOOSE", 3), ("COW", 3)],
    "mix_c3s3":     [("COW", 3), ("SHEEP", 3)],
}


def _cfg_key(name, kwargs):
    return {"name": name, "kwargs": kwargs}


def _score(entry):
    """Average mean-money across whichever opponents are present."""
    vals = [v["mean"] for v in entry["results"].values()]
    return sum(vals) / len(vals)


def run_screen(configs, n_episodes, episode_steps, tag):
    out = {}
    t_start = time.time()
    for i, (name, kwargs) in enumerate(configs.items()):
        agent = make_agent(**kwargs)
        res = {}
        for opp in OPPONENTS:
            res[opp] = run_matches(agent, opp, n_episodes=n_episodes, episode_steps=episode_steps)
        out[name] = {"kwargs": kwargs, "results": res}
        elapsed = time.time() - t_start
        avg = _score(out[name])
        print(f"[{i+1}/{len(configs)}] {name}: avg_mean={avg:.0f}  ({elapsed:.0f}s elapsed)", flush=True)
    path = RESULTS_DIR / f"{tag}.json"
    with open(path, "w") as f:
        json.dump(out, f, indent=2)
    print(f"Wrote {path}")
    return out


def phase_screen1():
    configs = {name: dict(animal_plan=plan) for name, plan in BASELINE_PLANS.items()}
    run_screen(configs, n_episodes=6, episode_steps=400, tag="screen1_baseline")


def phase_screen2():
    with open(RESULTS_DIR / "screen1_baseline.json") as f:
        screen1 = json.load(f)
    ranked = sorted(screen1.items(), key=lambda kv: _score(kv[1]), reverse=True)
    top_plans = ranked[:6]
    print("Top baseline plans:", [n for n, _ in top_plans])

    configs = {}
    # feed_mode x care_mode variants on top plans
    for name, entry in top_plans:
        plan = entry["kwargs"]["animal_plan"]
        for feed_mode in ("daily", "alternate"):
            for care_mode in ("always", "never"):
                if feed_mode == "daily" and care_mode == "always":
                    continue  # that's the baseline itself, already screened
                cname = f"{name}_feed-{feed_mode}_care-{care_mode}"
                configs[cname] = dict(animal_plan=plan, feed_mode=feed_mode, care_mode=care_mode)

    # collect_fert off, on best feed/care baseline
    for name, entry in top_plans[:4]:
        plan = entry["kwargs"]["animal_plan"]
        configs[f"{name}_nofert"] = dict(animal_plan=plan, collect_fert=False)

    # start_day variants
    for name, entry in top_plans[:3]:
        plan = entry["kwargs"]["animal_plan"]
        for sd in (2, 5, 8, 12):
            configs[f"{name}_start{sd}"] = dict(animal_plan=plan, start_day=sd)

    # hands scaling on the largest plans
    large_plans = [(n, e) for n, e in top_plans if sum(c for _, c in e["kwargs"]["animal_plan"]) >= 6][:3]
    if not large_plans:
        large_plans = top_plans[:2]
    for name, entry in large_plans:
        plan = entry["kwargs"]["animal_plan"]
        for nh in (1, 2):
            configs[f"{name}_hands{nh}"] = dict(animal_plan=plan, num_hands=nh)

    # staggered purchase vs unlimited
    for name, entry in top_plans[:3]:
        plan = entry["kwargs"]["animal_plan"]
        configs[f"{name}_stagger1"] = dict(animal_plan=plan, max_buy_per_day=1)

    # wheat slack buffer
    for name, entry in top_plans[:2]:
        plan = entry["kwargs"]["animal_plan"]
        configs[f"{name}_wheatslack3"] = dict(animal_plan=plan, buy_wheat_slack=3)

    print(f"Screening {len(configs)} variant configs")
    run_screen(configs, n_episodes=6, episode_steps=400, tag="screen2_variants")


def phase_confirm(top_k=18):
    with open(RESULTS_DIR / "screen1_baseline.json") as f:
        screen1 = json.load(f)
    with open(RESULTS_DIR / "screen2_variants.json") as f:
        screen2 = json.load(f)
    all_screened = {}
    all_screened.update(screen1)
    all_screened.update(screen2)
    ranked = sorted(all_screened.items(), key=lambda kv: _score(kv[1]), reverse=True)
    top = ranked[:top_k]
    print("Top configs going to confirmation:")
    for name, entry in top:
        print(f"  {name}: screen_avg={_score(entry):.0f}  kwargs={entry['kwargs']}")

    configs = {name: entry["kwargs"] for name, entry in top}
    run_screen(configs, n_episodes=30, episode_steps=720, tag="confirm_final")


if __name__ == "__main__":
    stage = sys.argv[1] if len(sys.argv) > 1 else "screen1"
    if stage == "screen1":
        phase_screen1()
    elif stage == "screen2":
        phase_screen2()
    elif stage == "confirm":
        phase_confirm()
    else:
        print("unknown stage", stage)
