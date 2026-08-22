"""Generate auditable counterfactual training pairs for the watcher SVM.

The baseline and intervention are separate deterministic replays.  A row is
accepted only when their checkpoint observations and all earlier focal-agent
actions hash identically.  This deliberately favours trustworthy examples
over forcing every requested deviation into the dataset.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import importlib
import json
import os
import random
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from kaggle_environments import make
from shared_features import FEATURE_ORDER, SCHEMA_HASH, extract_features


SCHEMA_VERSION = "counterfactual-v1"
CROPS = ("WHEAT", "CARROT", "TOMATO", "STRAWBERRY", "MELON")
ANIMALS = ("GOOSE", "COW", "SHEEP")
PRODUCTS = CROPS + ("EGG", "MILK", "WOOL")
STRUCTURES = ("COOP", "PASTURE")
SHOPS = ("BAKERY", "PIZZA_SHOP", "BRUNCH_SPOT", "YARN_STORE",
         "ICE_CREAM_SHOP", "PET_CAFE", "SMOOTHIE_SHOP", "FARMERS_MARKET")
BASE_PRICE = {"WHEAT": 25, "CARROT": 35, "TOMATO": 60, "STRAWBERRY": 120,
              "MELON": 250, "EGG": 50, "MILK": 160, "WOOL": 200}
THROUGHPUT = {"WHEAT": 400, "CARROT": 450, "TOMATO": 200, "STRAWBERRY": 100,
              "MELON": 300, "EGG": 332, "MILK": 122, "WOOL": 105}
DEVIATIONS = ("crop_add_two", "crop_remove_two", "crop_redirect_two",
              "animal_add_one", "animal_defer_one", "hand_add_one",
              "hand_remove_one", "land_advance", "land_defer",
              "premium_exit", "premium_retain")
ANIMAL_PRODUCT = {"GOOSE": "EGG", "COW": "MILK", "SHEEP": "WOOL"}


def checkpoint_specs(episode_steps=720, turns_per_day=24, unlock_interval=3):
    """Unique hour-zero checkpoints, with all coincident reason flags."""
    last_day = (episode_steps - 1) // turns_per_day
    rows = []
    for day in range(last_day + 1):
        reasons = ["day_start"]
        if day > 0 and day % unlock_interval == 0:
            reasons.append("shop_unlock")
        rows.append({"step": day * turns_per_day, "day": day, "hour": 0,
                     "reasons": reasons})
    return rows


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _hash(value):
    return hashlib.sha256(_canonical(value).encode()).hexdigest()


class RecordingAgent:
    def __init__(self, base, checkpoint_step, deviation=None):
        self.base, self.checkpoint_step, self.deviation = base, checkpoint_step, deviation
        self.pre_actions, self.checkpoint_obs, self.audit = [], None, {"attempted": 0, "applied": 0, "events": []}

    def __call__(self, obs):
        action = copy.deepcopy(self.base(obs))
        step = obs.get("step", obs["day"] * 24 + obs["hour"])
        if step < self.checkpoint_step:
            self.pre_actions.append(action)
        elif step == self.checkpoint_step and self.checkpoint_obs is None:
            self.checkpoint_obs = copy.deepcopy(obs)
        if self.deviation and step >= self.checkpoint_step:
            action = self._intervene(action, obs)
        return action

    def _intervene(self, action, obs):
        kind, item, target = self.deviation["kind"], self.deviation.get("item"), self.deviation.get("target")
        remaining = self.deviation.setdefault("remaining", 2 if "two" in kind else 1)
        if remaining <= 0: return action
        self.audit["attempted"] += 1
        market = action.setdefault("market", [])
        before = copy.deepcopy(action)
        if kind in ("crop_add_two", "animal_add_one", "hand_add_one", "land_advance"):
            order = (["BUY_SEED", item, remaining] if kind == "crop_add_two" else
                     ["BUY_ANIMAL", item, 1] if kind == "animal_add_one" else
                     ["HIRE"] if kind == "hand_add_one" else ["BUY_LAND"])
            if len(market) < 10: market.append(order); self.deviation["remaining"] = 0
        elif kind in ("crop_remove_two", "animal_defer_one", "hand_remove_one", "land_defer"):
            op = {"crop_remove_two": "BUY_SEED", "animal_defer_one": "BUY_ANIMAL",
                  "hand_remove_one": "HIRE", "land_defer": "BUY_LAND"}[kind]
            for i, order in enumerate(market):
                if order and order[0] == op and (op != "BUY_SEED" or order[1] == item):
                    qty = min(remaining, order[2] if len(order) > 2 else 1)
                    if len(order) > 2 and order[2] > qty: order[2] -= qty
                    else: market.pop(i)
                    self.deviation["remaining"] -= qty; break
        elif kind == "crop_redirect_two":
            for order in market:
                if order and order[0] == "BUY_SEED" and order[1] == item:
                    qty = min(remaining, order[2]); order[1] = target
                    if qty < order[2]: order[2] = qty
                    self.deviation["remaining"] -= qty; break
        elif kind == "premium_exit":
            market[:] = [o for o in market if not (o and len(o) > 1 and o[0] in ("BUY_SEED", "BUY_ANIMAL") and o[1] == item)]
            for key in ("farmer",):
                if action.get(key, [None])[0] == "PLANT" and action[key][1] == item: action[key] = ["PASS"]
            action["hands"] = [["PASS"] if a and a[0] == "PLANT" and a[1] == item else a for a in action.get("hands", [])]
        elif kind == "premium_retain":
            market[:] = [o for o in market if not (o and o[0] == "SELL" and o[1] == item)]
        if action != before:
            self.audit["applied"] += 1
            self.audit["events"].append({"step": obs.get("step"), "before": before, "after": copy.deepcopy(action)})
            if kind in ("premium_exit", "premium_retain"): self.deviation["remaining"] = 0
        return action


def _metrics(env, idx):
    feed = water = cap = overflow = missed = noops = 0
    escaped = 0
    previous_tiles = None
    for pair in env.steps:
        state = pair[idx]
        obs = state.observation
        farm = obs["farms"][idx]
        tiles = farm["tiles"]
        for y, row in enumerate(tiles):
            for x, tile in enumerate(row):
                if isinstance(tile, dict) and tile.get("kind") in STRUCTURES and tile.get("animal"):
                    feed += int(tile.get("consecutive_unfed", 0) > 0)
                elif isinstance(tile, dict) and tile.get("kind") == "PLANT":
                    water += int(tile.get("consecutive_unwatered", 0) > 0)
                if previous_tiles is not None:
                    old = previous_tiles[y][x]
                    if isinstance(old, dict) and old.get("kind") in STRUCTURES and old.get("animal"):
                        escaped += int(isinstance(tile, dict) and tile.get("kind") == old.get("kind") and not tile.get("animal"))
                    if isinstance(old, dict) and old.get("kind") == "PLANT" and old.get("consecutive_unwatered", 0) > 0:
                        missed += int(isinstance(tile, dict) and tile.get("kind") == "WEED")
        previous_tiles = tiles
        action = state.action or {}
        cap += int(len(action.get("market", [])) > 10)
    final_private = env.steps[-1][idx].observation.get("private", {})
    ending = sum(final_private.get("shed", {}).get(x, 0) for x in PRODUCTS)
    overflow = int(sum(final_private.get("shed", {}).values()) >= 100)
    return {"feed_risk_tile_turns": feed, "water_risk_tile_turns": water,
            "escaped_animals": escaped, "missed_watering_deaths": missed,
            "shed_overflow_indicators": overflow, "ending_saleable_inventory": ending,
            "invalid_noop_purchase_indicators": noops, "market_order_cap_violations": cap}


def label_delta(delta, safety_failure):
    if safety_failure or delta < -250: return -1
    if delta > 250: return 1
    return 0


def _run(base, opponent, idx, seed, steps, checkpoint, deviation=None):
    wrapped = RecordingAgent(base, checkpoint, copy.deepcopy(deviation))
    # Kaggle's callable preparation may copy callable instances.  A function
    # closure keeps the recorder identity visible to this process.
    def focal(observation):
        return wrapped(observation)
    agents = [focal, opponent] if idx == 0 else [opponent, focal]
    env = make("kaggriculture", configuration={"episodeSteps": steps, "seed": seed}, debug=False)
    env.run(agents)
    money = env.steps[-1][idx].observation["farms"][idx]["money"]
    return wrapped, env, money, _metrics(env, idx)


def random_deviation(rng):
    kind = rng.choice(DEVIATIONS)
    item = (rng.choice(CROPS) if "crop" in kind else rng.choice(ANIMALS) if "animal" in kind
            else rng.choice(("MELON", "STRAWBERRY", "MILK", "WOOL")) if "premium" in kind else None)
    target = rng.choice([x for x in CROPS if x != item]) if kind == "crop_redirect_two" else None
    return {"kind": kind, "item": item, "target": target, "remaining": 2 if "two" in kind else 1}


def modeled_output_id(deviation):
    """Map a single intervention to the one classifier it supervises."""
    kind, item = deviation["kind"], deviation.get("item")
    if kind == "crop_redirect_two":
        return f"product:{deviation['target']}:increase"
    if kind == "crop_add_two": return f"product:{item}:increase"
    if kind == "crop_remove_two": return f"product:{item}:avoid"
    if kind == "animal_add_one": return f"product:{ANIMAL_PRODUCT[item]}:increase"
    if kind == "animal_defer_one": return f"product:{ANIMAL_PRODUCT[item]}:avoid"
    if kind == "premium_exit": return f"product:{item}:avoid"
    if kind == "premium_retain": return f"product:{item}:increase"
    return "competitive_expansion"


def build_tasks(pairs, seed_base, opponents, episode_steps):
    """Construct the stable task order used by sequential and parallel runs."""
    return [{"pair_index": n, "seed": seed_base + n,
             "opponent_name": opponents[n % len(opponents)],
             "episode_steps": episode_steps} for n in range(pairs)]


def generate_pair(base, opponent, opponent_name, seed, pair_index, episode_steps=720):
    rng = random.Random((seed << 16) ^ pair_index)
    spec = rng.choice(checkpoint_specs(episode_steps))
    deviation = random_deviation(rng)
    idx = pair_index % 2
    b, benv, bm, bs = _run(base, opponent, idx, seed, episode_steps, spec["step"])
    i, ienv, im, ins = _run(base, opponent, idx, seed, episode_steps, spec["step"], deviation)
    state_match = b.checkpoint_obs is not None and _hash(b.checkpoint_obs) == _hash(i.checkpoint_obs)
    # Replay actions cover both players, including named built-in opponents.
    # Keep the wrapper-side focal audit too, as a guard against replay layout
    # changes in kaggle-environments.
    baseline_all_actions = [[state.action for state in pair] for pair in benv.steps[:spec["step"]]]
    intervention_all_actions = [[state.action for state in pair] for pair in ienv.steps[:spec["step"]]]
    action_match = (_hash(b.pre_actions) == _hash(i.pre_actions) and
                    _hash(baseline_all_actions) == _hash(intervention_all_actions))
    safety = any(ins[k] > bs[k] for k in ("escaped_animals", "missed_watering_deaths", "market_order_cap_violations"))
    applied = i.audit["applied"] > 0
    delta = im - bm
    return {"schema_version": SCHEMA_VERSION, "schema_hash": SCHEMA_HASH,
            "feature_order": list(FEATURE_ORDER), "features": extract_features(b.checkpoint_obs, episode_steps) if b.checkpoint_obs else None,
            "seed_group": seed, "seed": seed, "player_order": idx, "opponent": opponent_name,
            "checkpoint": spec, "deviation": deviation,
            "output_id": modeled_output_id(deviation), "intervention_audit": i.audit,
            "baseline_money": bm, "intervention_money": im, "delta": delta,
            "baseline_safety": bs, "intervention_safety": ins, "safety_failure": safety,
            "label": label_delta(delta, safety), "accepted": bool(state_match and action_match and applied),
            "rejection_reasons": [name for name, ok in (("checkpoint_state_mismatch", state_match),
                                                          ("pre_checkpoint_action_mismatch", action_match),
                                                          ("unapplied_or_infeasible", applied)) if not ok]}


def resolve_opponent(name):
    if name == "starter": return "starter"
    module_name = name.rsplit(".agent", 1)[0]
    # v2 agents intentionally support direct script execution and therefore
    # import their sibling as ``engine`` rather than package-relative.
    if module_name.startswith("strategies_v2.") and "engine" not in sys.modules:
        sys.modules["engine"] = importlib.import_module("strategies_v2.engine")
    module = importlib.import_module(module_name)
    return module.agent


def _generate_task(task):
    from strategy_follower import agent
    return generate_pair(agent, resolve_opponent(task["opponent_name"]),
                         task["opponent_name"], task["seed"], task["pair_index"],
                         task["episode_steps"])


def summarize_rows(rows):
    labels, outputs, rejections = Counter(), Counter(), Counter()
    for row in rows:
        if row["accepted"]:
            labels[str(row["label"])] += 1
            outputs[f"{row['output_id']}|{row['label']}"] += 1
        else:
            rejections.update(row["rejection_reasons"])
    return {"schema_version": SCHEMA_VERSION, "schema_hash": SCHEMA_HASH,
            "pairs": len(rows), "accepted": sum(r["accepted"] for r in rows),
            "rejected": sum(not r["accepted"] for r in rows),
            "class_counts": dict(sorted(labels.items())),
            "output_class_counts": dict(sorted(outputs.items())),
            "rejection_counts": dict(sorted(rejections.items()))}


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output", type=Path, default=Path("data/counterfactual_smoke.jsonl"))
    p.add_argument("--pairs", type=int, default=1)
    p.add_argument("--seed-base", type=int, default=0)
    p.add_argument("--episode-steps", type=int, default=720)
    p.add_argument("--workers", type=int, default=1,
                   help="worker processes; output remains in deterministic task order")
    p.add_argument("--opponents", nargs="+", default=["starter", "strategies_v2.ring.agent", "strategies_v2.leader_clone.agent"])
    args = p.parse_args(argv)
    tasks = build_tasks(args.pairs, args.seed_base, args.opponents, args.episode_steps)
    workers = min(max(1, args.workers), max(1, args.pairs), os.cpu_count() or 1)
    if workers == 1:
        rows = [_generate_task(task) for task in tasks]
    else:
        # executor.map preserves input order even when workers finish out of order.
        with ProcessPoolExecutor(max_workers=workers) as pool:
            rows = list(pool.map(_generate_task, tasks))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as fh:
        for row in rows: fh.write(json.dumps(row, separators=(",", ":")) + "\n")
    summary = summarize_rows(rows)
    summary_path = args.output.with_suffix(args.output.suffix + ".summary.json")
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    accepted = summary["accepted"]
    print(f"wrote {len(rows)} pairs ({accepted} accepted, {len(rows)-accepted} rejected) to {args.output}")
    print(f"wrote summary to {summary_path}")


if __name__ == "__main__":
    main()
