"""Two-phase sweep runner for the labor/land config leaderboard.

Phase 1 (screen): every config in configs.CONFIGS, n=8 episodes x 2
opponents x episode_steps=300. Cheap, used only to rank and prune.

Allocation supplement: take the top N_ALLOC_PROBE screening survivors and
re-screen them under the "quadrant" and "nearest" allocation modes (the
stripe mode is already covered in phase 1), so the allocation dimension
gets a fair look on strategies that are otherwise competitive.

Phase 2 (confirm): top N_CONFIRM configs (by combined screen score, across
both the original phase-1 pool and the allocation supplement) re-run at
n=30 episodes PER OPPONENT x episode_steps=720 -- this is what's reportable
in FINDINGS.md.

Uses a process pool since configs are fully independent; workers pass
config names (strings) across the process boundary and rebuild the agent
locally, since the policy closures in configs.py aren't picklable.
"""

import json
import os
import sys
import time
from multiprocessing import Pool

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))  # harmless if wrong
_ROOT = r"C:\Users\blazi\Kaggle\agriculture"
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

RESULTS_DIR = os.path.join(_HERE, "results")
os.makedirs(RESULTS_DIR, exist_ok=True)

N_SCREEN_EPISODES = 8
SCREEN_STEPS = 300
N_CONFIRM_EPISODES = 30
CONFIRM_STEPS = 720
N_CONFIRM_TOP = 20
N_ALLOC_PROBE = 6


def _build_agent(name, allocation_override=None):
    import configs as C
    from agent import make_agent
    cfg = C.get(name)
    alloc = allocation_override or cfg["allocation"]
    return make_agent(cfg["hire_fn"], cfg["land_fn"], alloc), cfg, alloc


def _screen_worker(args):
    name, allocation_override = args
    from harness import run_matches
    agent, cfg, alloc = _build_agent(name, allocation_override)
    t0 = time.time()
    vs_random = run_matches(agent, "random", n_episodes=N_SCREEN_EPISODES, episode_steps=SCREEN_STEPS)
    vs_starter = run_matches(agent, "starter", n_episodes=N_SCREEN_EPISODES, episode_steps=SCREEN_STEPS)
    elapsed = time.time() - t0
    combined = 0.5 * vs_random["mean"] + 0.5 * vs_starter["mean"]
    label = name if allocation_override is None else f"{name}__alloc_{allocation_override}"
    return {
        "label": label, "base_name": name, "allocation": alloc,
        "vs_random": vs_random, "vs_starter": vs_starter,
        "combined_screen_score": combined, "elapsed_sec": elapsed,
    }


def _confirm_worker(args):
    name, allocation_override = args
    from harness import run_matches
    agent, cfg, alloc = _build_agent(name, allocation_override)
    t0 = time.time()
    vs_random = run_matches(agent, "random", n_episodes=N_CONFIRM_EPISODES, episode_steps=CONFIRM_STEPS)
    vs_starter = run_matches(agent, "starter", n_episodes=N_CONFIRM_EPISODES, episode_steps=CONFIRM_STEPS)
    elapsed = time.time() - t0
    combined = 0.5 * vs_random["mean"] + 0.5 * vs_starter["mean"]
    label = name if allocation_override is None else f"{name}__alloc_{allocation_override}"
    return {
        "label": label, "base_name": name, "hire": cfg["hire"], "land": cfg["land"], "allocation": alloc,
        "vs_random": vs_random, "vs_starter": vs_starter,
        "combined_score": combined, "elapsed_sec": elapsed,
    }


def main():
    import configs as C

    all_names = [c["name"] for c in C.CONFIGS]
    print(f"Phase 1: screening {len(all_names)} configs "
          f"(n={N_SCREEN_EPISODES}/opponent, steps={SCREEN_STEPS})...", flush=True)

    t0 = time.time()
    with Pool(processes=min(16, os.cpu_count() or 4)) as pool:
        screen_results = pool.map(_screen_worker, [(n, None) for n in all_names])
    print(f"Phase 1 done in {time.time()-t0:.1f}s", flush=True)

    screen_results.sort(key=lambda r: r["combined_screen_score"], reverse=True)
    with open(os.path.join(RESULTS_DIR, "screen_results.json"), "w") as f:
        json.dump(screen_results, f, indent=2)

    print("\nTop 15 after phase 1 (stripe allocation, screening scale):")
    for r in screen_results[:15]:
        print(f"  {r['label']:35s} combined={r['combined_screen_score']:.0f}  "
              f"vs_random={r['vs_random']['mean']:.0f}  vs_starter={r['vs_starter']['mean']:.0f}")

    # --- Allocation supplement: re-screen top N_ALLOC_PROBE under quadrant/nearest ---
    probe_names = [r["base_name"] for r in screen_results[:N_ALLOC_PROBE]]
    alloc_jobs = [(n, mode) for n in probe_names for mode in ("quadrant", "nearest")]
    print(f"\nAllocation supplement: probing {len(alloc_jobs)} (config, allocation) pairs "
          f"on top {N_ALLOC_PROBE} screening survivors...", flush=True)
    t0 = time.time()
    with Pool(processes=min(16, os.cpu_count() or 4)) as pool:
        alloc_results = pool.map(_screen_worker, alloc_jobs)
    print(f"Allocation supplement done in {time.time()-t0:.1f}s", flush=True)
    with open(os.path.join(RESULTS_DIR, "allocation_screen_results.json"), "w") as f:
        json.dump(alloc_results, f, indent=2)

    for r in sorted(alloc_results, key=lambda r: r["combined_screen_score"], reverse=True):
        print(f"  {r['label']:45s} combined={r['combined_screen_score']:.0f}")

    # --- Merge pools, pick confirmation set ---
    merged = screen_results + alloc_results
    merged.sort(key=lambda r: r["combined_screen_score"], reverse=True)

    # Dedupe: keep best allocation per base_name only if it's a genuine improvement
    # over that base_name's stripe result; otherwise just carry stripe forward.
    seen_base = set()
    confirm_jobs = []
    for r in merged:
        key = r["base_name"]
        if key in seen_base:
            continue
        seen_base.add(key)
        confirm_jobs.append((r["base_name"], None if r["allocation"] == "stripe" else r["allocation"]))
        if len(confirm_jobs) >= N_CONFIRM_TOP:
            break

    print(f"\nPhase 2: confirming top {len(confirm_jobs)} configs "
          f"(n={N_CONFIRM_EPISODES}/opponent, steps={CONFIRM_STEPS})...", flush=True)
    t0 = time.time()
    with Pool(processes=min(16, os.cpu_count() or 4)) as pool:
        confirm_results = pool.map(_confirm_worker, confirm_jobs)
    print(f"Phase 2 done in {time.time()-t0:.1f}s", flush=True)

    confirm_results.sort(key=lambda r: r["combined_score"], reverse=True)
    with open(os.path.join(RESULTS_DIR, "confirm_results.json"), "w") as f:
        json.dump(confirm_results, f, indent=2)

    print("\n=== CONFIRMED LEADERBOARD (n=30/opponent, 720 steps) ===")
    for r in confirm_results:
        print(f"  {r['label']:40s} combined={r['combined_score']:.0f}  "
              f"vs_random(mean/med/sd)={r['vs_random']['mean']:.0f}/{r['vs_random']['median']:.0f}/{r['vs_random']['stdev']:.0f}  "
              f"vs_starter(mean/med/sd)={r['vs_starter']['mean']:.0f}/{r['vs_starter']['median']:.0f}/{r['vs_starter']['stdev']:.0f}")


if __name__ == "__main__":
    main()
