# Replay-Guided SVM Training Plan

## Summary

Refresh the Kaggle leaderboard, collect public replays for the current top 10 submissions, and use their successful trajectories to guide the existing counterfactual generator. Replays will determine which states and interventions receive training emphasis, while final SVM labels remain causal differences from paired simulations.

Top-contestant wins receive twice the sampling weight of losses. Losses remain available to identify failure boundaries. Duplicate strategies are collapsed into equal-weight strategy families so copied agents cannot dominate training.

## Replay Corpus and Features

- Refresh the leaderboard and freeze a timestamped manifest containing the top 10 submission IDs, ranks, teams, and up to 150 completed public episodes per submission.
- Download missing raw replays idempotently and reject incomplete, malformed, non-720-turn, or mismatched-team episodes.
- Deduplicate by episode/player slot and cluster exact strategy duplicates using normalized opening actions plus checkpoint farm-layout fingerprints. Give every distinct strategy family equal total weight.
- Extract the state preceding each action at day starts and shop unlocks, preserving the existing replay alignment rule that `steps[t-1].observation` caused `steps[t].action`.
- Use exactly the runtime-safe SVM feature schema. Include the focal contestant's private inventory but never the opponent's private fields.
- Record rank, family, win/loss, final money, margin, checkpoint reason, feature vector, and asset changes before the next checkpoint.
- Convert observed changes into expert intervention proposals: product increase/avoid, animal add/defer, labor change, land timing, and premium-product retain/exit.

## Replay-Guided Counterfactual Labels

- Extend the counterfactual generator to sample strategy families uniformly, then sample winning episodes at a 2:1 rate over losses.
- Condition checkpoint phase, output type, product, and intervention direction on the replay-derived expert distribution.
- For every selected expert proposal, simulate both the expert-consistent intervention and its bounded opposite when feasible. Baseline and intervention must share seed, player order, state, RNG path, and actions through the checkpoint.
- Continue using `starter`, `ring`, and `leader_clone` as executable opponents; leaderboard replays guide scenario selection rather than pretending an unavailable contestant binary can be replayed.
- Derive labels only from paired final-money results:
  - `+1`: improvement greater than $250 with no safety regression.
  - `-1`: loss greater than $250 or any safety failure.
  - `0`: otherwise.
- Retain neutral and rejected rows for auditing, but exclude them from binary `LinearSVC` fitting.
- Add replay provenance and normalized sample weight to every generated row. Equalize total weight by strategy family, apply the 2:1 win preference within each family, normalize mean accepted-row weight to 1.0, and clip individual weights to `[0.5, 2.0]`.
- Generate deterministic seed-range batches until every modeled output has at least 150 accepted examples, including at least 40 positive and 40 negative labels, or reaches the 2,000-pair cap. Unsupported outputs remain on the deterministic rules backend.

## Training, Export, and Acceptance

- Split replay strategy families into 60% training, 20% validation, and 20% test groups before counterfactual generation. Keep each replay episode, simulation seed, and duplicate strategy family from crossing splits.
- Fit scalers on training data only. Train independent class-balanced `LinearSVC` models for each product increase/avoid output and competitive expansion, passing replay-derived sample weights.
- Report unweighted and weighted balanced accuracy, confusion matrices, class counts, majority baselines, and leave-one-strategy-family-out results.
- Export only models with test balanced accuracy of at least `0.60` and at least `0.10` above their majority baseline. Export feature order, scaler values, coefficients, intercepts, margin scales, schema hash, and replay snapshot metadata as pure-Python constants.
- Integrate exported inference into `strategy_follower.py` with deterministic-rule fallback for missing models, schema mismatch, or non-finite output. Do not modify `main.py` during this phase.
- Promote only after paired full-season confirmation against `starter`, `ring`, and `leader_clone`: at least 30 episodes per opponent, overall 95% paired-money confidence interval above zero, no confirmed opponent regression over 1%, and no safety-gate regression. Expand inconclusive comparisons once to 60 episodes.

## Verification

- Test leaderboard refresh failure, resumable downloads, replay integrity, duplicate-family detection, player-slot resolution, pre-action alignment, checkpoint deduplication, and opponent-private-field exclusion.
- Test deterministic replay sampling, equal family weighting, 2:1 win weighting, intervention inversion, label boundaries, safety overrides, batch merging, and split leakage prevention.
- Verify schema hashes and finite feature vectors across replay and simulation records.
- Reproduce training from the frozen manifest and seed configuration.
- Produce corpus, class-balance, model-evaluation, and gameplay-comparison summaries. If leaderboard refresh or Kaggle authentication fails, stop without silently substituting the stale local snapshot.

## Assumptions

- "Top contestants" means the current top 10 at execution time, frozen into a reproducible manifest.
- Top-contestant data is outcome-weighted rather than wins-only.
- Exact duplicate strategies count as one family.
- Replays guide state and intervention distributions; paired simulations remain the sole source of causal SVM labels.
- Existing replay files are incomplete locally (31 of 1,009 known episodes), so collection must restore the raw corpus first.
