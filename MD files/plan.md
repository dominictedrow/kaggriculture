# Harness wiring + strategy follower (combined livestock + melon)

## Context

Architecture v2 (per `CLAUDE.md`) has three parts: the harness, the strategy
follower, and the watcher. Dom asked for the first two now, explicitly kept
"fairly simple," and said the watcher is the piece he wants more input on
later — so this plan builds only the harness and strategy follower.

Two concrete asks:
- **Harness**: keep the existing `run_matches()` interface/shape (Dom: "otherwise
  the same as most other harnesses"), just make it fast.
- **Strategy follower**: "really just a step by step action layout," and
  "adaptable... easy to change as my strategy evolves." Dom picked the
  **combined livestock + melon** ruleset (higher ceiling, flagged as
  "untested, worth trying" in `CONSOLIDATED_FINDINGS.md` — not yet a confirmed
  number, unlike the pure-livestock #1 result).

Both existing phase-1 engines (`strategies/livestock/agent_lib.py`,
`strategies/crops/engine.py`) already contain proven-correct logic for their
half of this. I read both in full. I'm not importing either directly into the
new files — see "Why not reuse the phase-1 engines directly" below — but the
new logic is a direct transcription of their validated rules, not a
from-scratch reinvention.

## 1. `harness.py` — parallelize episodes (stdlib only)

Current `run_matches()` loops `n_episodes` times sequentially, calling
`kaggle_environments.make(...)` fresh each iteration. That's the only real
speed lever available without changing the interface: episodes are fully
independent (fresh env each time already), so this is an embarrassingly
parallel workload — exactly what `concurrent.futures.ProcessPoolExecutor`
(stdlib, no new dependency) is for.

Changes:
- Extract the per-episode body into a new **top-level** function
  `_run_episode(agent, opponent, agent_idx, episode_steps)` (must be
  module-level, not nested, so it's picklable for `spawn`-based multiprocessing
  on Windows).
- `run_matches(agent, opponent, n_episodes, episode_steps=720, n_workers=None)`:
  submit one `_run_episode` task per episode to a
  `ProcessPoolExecutor(max_workers=min(n_workers or os.cpu_count(), n_episodes))`,
  collect the money results, compute the same
  `{n, mean, median, min, max, stdev}` dict as today. Signature and return
  shape unchanged except for the new optional `n_workers` kwarg.
- Keep `_final_money()` as-is, called inside `_run_episode`.
- `_demo()` self-check stays (still `"pass"` vs `"random"`, both trivially
  picklable strings) — this remains the harness's own regression check.

Two things worth calling out (as comments in the code, not extra machinery):
- `kaggle_environments` is an expensive import (pulls in OpenSpiel, which
  dumps a huge game-list on load). `ProcessPoolExecutor` pays that cost once
  per **worker process** (reused across all tasks assigned to it), not once
  per episode — so the parallel version is a net win once `n_episodes` is
  meaningfully larger than core count (true for any real n>=30 confirmation
  run), even though a tiny smoke-test run (n=1-2) won't see much benefit.
- `# ponytail:` comment noting the real limitation: `ProcessPoolExecutor`
  needs picklable callables. Plain top-level functions and built-in strings
  (`"random"`, `"starter"`, a file path) work fine. The phase-1 sweep
  engines' `make_agent(...)` factories return **closures**, which do not
  pickle — so self-play against an old phase-1 config would need that config
  rebuilt inside the worker (factory + kwargs passed separately), not
  attempted here since it wasn't asked for. `strategy_follower.agent` (below)
  is written as a plain top-level function specifically so it doesn't hit
  this problem.
- Any caller of `run_matches` needs its own `if __name__ == "__main__":`
  guard (standard Windows/spawn requirement) — already true for `_demo()`.

## 2. `strategy_follower.py` (new, project root) — combined livestock + melon

Plain top-level `agent(obs)` function (no factory/closure — matches "step by
step action layout," and stays picklable for the parallel harness above).
Structure, top to bottom:

**Constants block** (the "easy to change" knobs):
```python
ANIMAL_MIX = {"COW": 4, "SHEEP": 2}   # both use PASTURE; roster from the #1 confirmed livestock finding
LIVESTOCK_HANDS = 2                    # proven 3-unit/6-tile ratio (farmer + 2 hands)
MELON_HANDS = 1                        # 1 unit alone covers ~12-20 melon tiles per crops findings' density-ceiling note
MAX_MELON_TILES = 19                   # NW quadrant (25) minus livestock's 6 -- fits with zero BUY_LAND
MELON_YIELD_DAY = 10                   # melon: first_yield_day == max_yield_day == 10 (RULES.md Object Types)
```
Bumping `MAX_MELON_TILES` past 19 or adding a `LAND` policy to expand into NE
is a deliberate future step, not built now (comment marks this).

**Tile plans** (pure functions of `obs`, no persistent state — every
kaggriculture agent call must be stateless since only `obs` is passed in):
- `_livestock_tiles()`: first 6 cells of the NW scan order backward from
  (4,4) — identical to `agent_lib.py`'s `_POSITIONS[:6]`, since farmer spawns
  there and it's shed-adjacent.
- `_melon_tiles()`: first `MAX_MELON_TILES` cells of the NW quadrant in
  forward row-major order, **excluding** any cell already claimed by
  `_livestock_tiles()` — explicit exclusion rather than relying on the two
  scan directions happening not to collide, since 6+19=25 exactly fills NW
  and an unguarded overlap would be a real (silent) bug.
- Crew split: farmer + hands[0] + hands[1] → livestock (2 tiles each, same
  chunking as the proven config); hands[2] (if hired/alive) → melon, alone,
  covering all `MAX_MELON_TILES` tiles.

**Livestock unit action** (adapted from `agent_lib.py::_unit_action`,
simplified since both COW and SHEEP use PASTURE — no COOP/GOOSE branching
needed for this roster):
1. On an assigned empty tile + carrying that animal → `PLACE <animal>`; tile
   is `None` → `BUILD_PASTURE` first.
2. On an assigned occupied tile, not fed today, carrying WHEAT → `FEED`.
3. Fed today, `yield_units > 0` → `HARVEST`.
4. Nothing to harvest, `fertilizer_available` → `COLLECT_FERTILIZER`.
5. Fed today, not cared today → `CARE`.
6. On a shed-adjacent tile: `PICKUP WHEAT` (enough for the whole chunk in one
   visit) or `PICKUP <animal>` for any still-missing animal.
7. Otherwise step toward the nearest assigned tile with a pending need (or
   back to shed if wheat/animal is needed and not carried).

**Melon unit action** (adapted from `engine.py::_tile_action`, melon-only):
1. Tile `None` → `PLANT MELON`.
2. Tile is a weed → `DIG`.
3. Tile is a melon plant, `age = day - planted_day`: `age >= 10 and
   yield_units > 0` → `HARVEST`; else if not watered today → `WATER`.
4. Otherwise step toward the nearest melon tile with a pending need.
   (No shed visits needed — seeds land directly in the `seeds` slot per
   `BUY_SEED`, same as `engine.py`'s existing agent.)

**Market orders every turn**:
- `SELL` every non-WHEAT shed item in full (dump-immediate — matches both
  source strategies' proven sell tactic; not adding the gating logic
  `CONSOLIDATED_FINDINGS.md` floats as "worth testing," since that's a tuning
  question for later, not part of transcribing the confirmed rules).
- At hour 0: `HIRE` × (`LIVESTOCK_HANDS + MELON_HANDS`) = 3.
- Buy missing COW/SHEEP up to `ANIMAL_MIX`, capped by affordability.
- `BUY_PRODUCT WHEAT` to cover exactly `sum(ANIMAL_MIX.values())` (6) held +
  shed wheat, no slack (matches the proven no-slack rule).
- `BUY_SEED MELON` to cover every currently-empty melon tile.
- No `BUY_LAND` (v1 fits entirely in the starting NW quadrant).

**Self-check** (`if __name__ == "__main__":`): run one short episode via
`kaggle_environments.make("kaggriculture", configuration={"episodeSteps": 100}).run([agent, "random"])`,
assert it completes without exceptions and final farm money is a
non-negative number, print the result. This is the one required runnable
check for non-trivial branching logic.

### Why not reuse the phase-1 engines directly

`CLAUDE.md` frames phase-1 code as "reference data... not the agent itself"
for this build phase, and two concrete things break if I import
`make_agent(...)` directly instead of transcribing:
1. It returns a closure, which isn't picklable — breaks the parallel harness
   above (see the `ponytail:` note in section 1).
2. It's a generic config-driven engine; Dom asked for a flat, readable,
   directly-editable script for this piece specifically, not another layer
   on the existing abstraction.

## Verification

1. `python harness.py` — confirms the parallelized `_demo()` self-check still
   passes and returns a sane stats dict.
2. `python strategy_follower.py` — runs the built-in self-check (100-step
   episode vs `"random"`), confirms no exceptions and plausible final money.
3. A small exploratory run (not a full statistical confirmation — n=8, not
   the n=30 phase-1 standard):
   `harness.run_matches(strategy_follower.agent, "starter", n_episodes=8, episode_steps=720)`,
   reported back to Dom as a first read on whether the combined build clears
   the $50,316 pure-livestock baseline. Framed explicitly as exploratory,
   since this combo has no confirmed number yet.
4. Confirm no new dependencies were added — everything here is stdlib
   (`concurrent.futures`, `os`) plus the already-installed
   `kaggle_environments`.
