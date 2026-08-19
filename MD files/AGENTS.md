# Repository Guidance

## Project purpose

This repository develops and evaluates a submission for Kaggle's two-player
Kaggriculture environment. The objective is to maximize the submitted agent's
final money over a 30-day, 720-turn season; the current aspirational target is
more than 110,000.

`CLAUDE.md` is the authoritative project brief. Preserve its central workflow
constraint: the user is designing the submitted model piece by piece. Do not
scaffold, add, or wire up the harness, strategy follower, watcher, training or
evaluation code, dependencies, or files until the user explicitly requests
that specific work. Research and prior strategies are reference material, not
implicit authorization to implement the next phase.

## Repository map

- `main.py`: current single-file Kaggle submission.
- `strategy_follower.py`: editable/full version of the opponent-blind strategy,
  including its demo. It is closely related to `main.py` but intentionally not
  byte-identical.
- `harness.py`: shared multiprocessing simulation and paired-comparison tools.
- `test_gen.py`: generates constant-overridden variants under `ab_tests/` and
  runs screening experiments.
- `RULES.md`: local game mechanics and economics reference.
- `CLAUDE.md`: current architecture, goal, and implementation boundaries.
- `1st.md`, `strategy.md`, `plan.md`, `report.md`: current analysis and design
  history; consult the relevant document before changing strategy behavior.
- `CONSOLIDATED_FINDINGS.md` and `strategies/*/FINDINGS.md`: completed phase-1
  search results. Treat their numbers as baseline evidence against weak
  opponents, not as validation against competitive agents.
- `strategies/`: phase-1 domain experiments and sweep code.
- `strategies_v2/`: later strategy/checker/comparison experiments.
- `ab_rounds/`: checked-in experiment configurations/results.
- `ab_tests/`: generated variants and results; ignored by Git and safe to
  recreate through `test_gen.py`.
- `kaggle_replays/`: replay acquisition and offline leaderboard-agent analysis.
  Its nested `AGENTS.md` supplies additional instructions for work in that
  subtree and takes precedence there.
- `.claude/scheduled_tasks.lock`: Claude session state, not project source. Do
  not edit or rely on it as durable configuration.

## Environment and dependencies

- Use Python 3.11.
- Runtime/evaluation dependencies are `kaggle-environments`; replay and CLI
  workflows also use `kaggle`, and historical analysis may use `numpy`.
- There is currently no package manifest or formal formatter/linter config.
  Do not introduce one unless requested.
- Keep submission code self-contained and compatible with Kaggle's loader and
  multiprocessing. Agent callables passed to `ProcessPoolExecutor` must be
  plain, top-level, picklable functions; factory closures are unsuitable.

## Critical submission invariant

Kaggle executes a submission file and selects its last top-level callable.
Therefore, in `main.py` and any directly submitted/generated agent file:

- `agent(obs)` must remain the last top-level callable definition.
- Do not define helpers, demo functions, or other callables below `agent`.
- Preserve the action shape: `{"farmer": [...], "hands": [[...], ...],
  "market": [[...], ...]}`.
- Remember that invalid actions and market orders beyond the per-turn cap can
  fail silently; tests must verify behavior, not merely absence of exceptions.

## Working conventions

- Make the smallest requested change and preserve the user's existing design.
- Read `RULES.md` and the relevant findings/design notes before changing game
  economics, timing, routing, purchase order, or market behavior.
- Keep configurable strategy values in the existing top-level constants when
  practical so `test_gen.py` can substitute them.
- Preserve deterministic seeded comparisons and alternating player order.
- Do not hand-edit generated files in `ab_tests/`; change the source or round
  configuration and regenerate them.
- Treat replay JSON, logs, result JSON/CSV, and historical findings as data.
  Avoid bulk rewrites or deletion unless explicitly requested.
- The worktree may contain active user experiments. Do not revert, overwrite,
  or clean unrelated modifications and untracked files.
- Keep Git/Kaggle submission, upload, and other external mutations in the
  primary agent and perform them only when explicitly requested.

## Verification

Match verification effort to the change:

- Harness smoke check: `python harness.py`
- Editable strategy smoke check: `python strategy_follower.py`
- Variant-generator smoke check: `python test_gen.py`
- Configured screening run: `python test_gen.py <round-config.json> [n_episodes]`
- Syntax check for touched Python files: `python -m py_compile <files...>`

Strategy conclusions require seeded paired evaluation with
`harness.compare_paired`, alternating player order and at least 20 episodes per
side. Use larger confirmation samples (historically at least 30 per opponent)
for claims recorded as validated. Report the paired difference, sample size,
opponents, and variance/range; do not select a strategy from an unpaired mean
alone. Lightweight smoke runs may use fewer episodes but must not be presented
as performance evidence.

Avoid running multiple variant scripts concurrently: each variant already
parallelizes episodes across CPU cores. For submission-affecting changes,
verify both the source strategy and the final `main.py` artifact, including the
last-callable invariant.
