# Kaggriculture — submitted agent (model design phase)

Phase 1 (strategy search, see `start.md` / `CONSOLIDATED_FINDINGS.md` /
`strategies/*/FINDINGS.md`) is done and stays as reference data — candidate
rules/numbers to draw on, not the agent itself. This phase builds the actual
submitted agent.

**Caveat on phase 1 numbers:** they were earned against `random` and
`starter`, both near-inert (`starter` farms one carrot tile, never hires;
`random` never hires a hand, plants ~30%/turn). Real opponents can sell at
volumes phase 1 never stress-tested — see "Why the watcher matters" below.

## Goal

Win the competition. Target: final money > 110,000 by end of the 30-day
season. Optimization target is the agent's own final money (see `harness.py`).

## Architecture v2 (Dom's design, subject to change as he refines it)

Three parts:

1. **The harness** — executes whatever action the other two parts decide on.
2. **The strategy follower** — a script that follows a predetermined set of
   rules/actions (drawn from phase-1 findings) intended to maximize profit on
   its own, opponent-blind.
3. **The watcher** — a model (form TBD) that watches the opponent's public
   farm state and the shared market (price + inventory), decides whether the
   situation calls for deviating from the strategy follower's plan, and if so
   supersedes it for that turn.

## Why the watcher matters (research, not opinion)

Checked directly against `RULES.md`'s price function and the installed
`kaggle_environments` source:

- Market inventory is **shared** — both players' sells drain/fill the same
  pool, and orders interleave one unit at a time, so the opponent's volume
  directly sets the price you get.
- **Melon has zero town demand** (not in any shop's demand table) and
  `above_target = 3.6` with `T = 300` — a glut craters its price and nothing
  meaningfully pulls it back for the rest of the season. Wool (`above_target
  = 3.2`) and milk (`1.6`) are similarly glut-fragile, with only partial shop
  coverage.
- Phase 1's best strategies (melon-mono, cow+sheep) were only validated
  against opponents that don't produce or sell at real volume. A competent
  real opponent converging on the same obviously-strong resources (melon is
  the highest-base-price crop; livestock's math isn't hidden either) could
  crash the shared price in a way phase 1 never observed.
- The opponent isn't a black box: `farms` (their tiles/crops/money/hands/
  unlocked_quadrants) is public in the observation every turn. Only their
  `shed`/`seeds` inventory is private. So the watcher is reading mostly-public
  state plus a fully known price formula, not inferring from noise.

## How we build this

Dom is designing the majority of this model himself, piece by piece, so he
knows exactly what's in it and how it functions when it's time to debug and
train. Do not scaffold, add, or wire up any component (harness wiring, the
strategy-follower script, the watcher model, training/eval code, files,
dependencies) ahead of an explicit request for that specific piece. No
anticipating next steps. Wait for his concrete instructions, data, and design
details before implementing.
