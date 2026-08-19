# Kaggriculture strategy search — start.md

## Goal (revised)

Not building or submitting a final agent. The job is: test **hundreds of distinct
farming strategies** for Kaggriculture via local simulation, rank them by how much
money they end the 30-day season with, and report the best performers back to Dom —
with enough detail (exact rules/parameters/numbers) that **he** designs and implements
his own submitted agent from the findings. No reference agent, no synthesis into "the"
implementation — that step is explicitly his, not mine.

## Setup

- Reuse the existing empty conda env `agric` (`C:\Users\blazi\miniconda3\envs\agric`):
  install `python=3.11`, then via pip `kaggle-environments`, `kaggle` (CLI), `numpy`.
- Kaggle auth: no credentials present yet. Dom sets this up himself — either
  `kaggle auth login` (browser OAuth, run via `!` prefix) or saving his own token to
  `~/.kaggle/access_token`. I won't handle the raw token text.
- Flag but don't touch: identity verification and competition rules acceptance shown on
  the Kaggriculture page — both require Dom's own action.
- Save the fetched "How to Play" rules to `RULES.md` in the project root so every
  research agent reads the same file instead of re-fetching Kaggle.
- Sanity check: run one local episode (`random` vs `starter`) through
  `kaggle_environments` and confirm it produces sane final-money numbers before any
  strategy search starts.

## Shared harness

One file, `harness.py`, at the project root:

- `run_matches(agent, opponent, n_episodes, episode_steps=720) -> stats` — runs N
  episodes via `kaggle_environments`, returns mean/median/min/max/stdev of the agent's
  **own final money** (the actual optimization target — not win/loss).
- Runs both player-order assignments (agent as P0 and P1).
- Plain stdlib + numpy only.

## Strategy search — 4 parallel agents, hundreds of strategies total

Spawn 4 `general-purpose` agents in parallel, each owning one domain/subdirectory so
there's no file overlap. Each is told explicitly: **generate and test many distinct
concrete strategies in your domain — not a handful of tweaks.** Aim for roughly 50-100+
genuinely different configurations per agent (different planting mixes, watering/
fertilizing thresholds and timing, hiring cadences, land-buy timing, sell-bundling
rules, feed/care schedules, etc.), so the four agents collectively cover on the order of
hundreds of strategies.

Domains:

1. `strategies/crops/` — one-time crops (wheat/carrot/melon): density, watering/
   fertilizing discipline, land-expansion timing by crop ROI.
2. `strategies/livestock/` — ongoing animal products (goose/cow/sheep): coop/pasture
   build order, feed/care discipline and the CARE bonus-banking mechanic.
3. `strategies/market/` — selling/buying tactics: order bundling/timing to avoid
   crashing your own price, exploiting town shop demand growth, wheat/fertilizer buy
   timing, working each resource's different price curve.
4. `strategies/labor_land/` — farm-hand hiring economics (Fibonacci daily cost reset),
   land-purchase ROI/timing, multi-hand task allocation, day-by-day reinvestment
   schedule.

Each agent maintains a **ranked leaderboard** in its own `FINDINGS.md`: every
configuration tested, its avg final money, sample size (n>=30 episodes/config), tested
against both `"random"` and `"starter"` baseline opponents (market is shared, so
opponent behavior affects prices — robustness matters). Top 5-10 entries get a clear
description of the exact rule/parameters (pseudocode-level, reimplementable), not just a
number.

## Consolidation (light touch, done by me — not a new agent)

- Merge all 4 domains' leaderboards into one overall ranked list.
- Call out the single best strategy and runner-ups across domains, with numbers and the
  mechanism behind why each worked.
- Present this ranked report to Dom. No `main.py`, no submission, no "here's the agent I
  built for you" — the report is the deliverable.

## Verification

- Local engine sanity run succeeds before research starts.
- Every leaderboard entry shows its sample size and opponent(s) tested against.
- Final consolidated ranking is shown to Dom with clear numbers before calling this done.
