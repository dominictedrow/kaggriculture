# Replay-to-SVM Training Data Plan

## Summary

Replay translation has not occurred yet. Existing replay analyses produce strategy summaries, while `counterfactual_dataset.jsonl` uses randomly selected simulations and contains no replay provenance, family weighting, or expert-guided interventions.

Build a two-stage pipeline: convert accepted leaderboard trajectories into observational expert proposals, then use those proposals to guide paired simulations that produce causal SVM labels. Replays must never directly supply `+1/-1` labels.

## Implementation Changes

- Use only the 852 accepted replays in the frozen corpus status. Keep the 55 team-mismatched and 180 unavailable episodes excluded but reported.
- Resolve every focal trajectory as `(episode_id, player_slot, submission_id)`. Preserve both slots in genuine self-play and collapse duplicate references to the same tuple.
- Preserve causal alignment exactly: for action record `steps[t].action`, use `steps[t-1].observation` as its source state. Select checkpoints when that source observation is a day start or newly unlocked-shop state.
- Move `FEATURE_ORDER`, `SCHEMA_HASH`, and `extract_features()` into one shared feature module, re-exporting them from `counterfactual_dataset.py` for compatibility. Extract features solely from the focal slot's observation: focal private inventory is allowed; the other slot's private observation is never read.

### Expert trajectory dataset

Produce a versioned JSONL dataset with one row per focal checkpoint containing:

- Replay, submission, rank, player slot, checkpoint step/day/reasons, schema hash, and feature vector.
- Win/loss/tie, focal and opponent final money, and margin.
- Focal asset, inventory, labor, land, action, and market-order changes through the next checkpoint.
- One or more explicit proposals: product increase/avoid or redirect, animal add/defer, labor add/remove, land advance/defer, and premium-product retain/exit.
- Proposal evidence and feasibility fields; ambiguous observations remain audit rows and are not sampled.

Derive proposals only from confirmed actions and state changes. For example, purchases plus new productive slots support "increase," removals or redirection support "avoid," and animal/labor/land changes must appear in subsequent state rather than merely as possibly invalid orders.

### Strategy families and splits

- Create a normalized trajectory fingerprint from the first 72 causally aligned actions and farm-layout fingerprints at later day-start checkpoints. Preserve operation, item, and bounded quantity while ignoring transient tile fields such as watered/fed flags and yield counters.
- For each submission, form a modal signature across its trajectories. Merge submissions only when their complete modal signatures match exactly; low-support or ambiguous cases remain separate families.
- Assign whole strategy families deterministically to 60% training, 20% validation, and 20% test groups, balancing trajectory counts as closely as possible. A replay episode, focal trajectory, family, and simulation seed may occur in only one split.
- Retain ties for auditing but do not use them in the win/loss proposal sampler.

### Replay-guided causal rows

Extend the counterfactual task schema with replay proposal provenance, family, split, output ID, direction, and weight.

For each sampled proposal:

1. Sample strategy families uniformly.
2. Within a family, sample winning trajectories twice as often as losing trajectories.
3. Condition simulation checkpoint phase, output/product, and intervention direction on the selected proposal.
4. Run one baseline, the expert-consistent bounded intervention, and its bounded opposite against `starter`, `ring`, or `leader_clone`.
5. Use identical seed, player order, RNG path, checkpoint state, and all pre-checkpoint actions.
6. Emit one causal row for each feasible direction; retain infeasible or state-mismatched attempts as rejected audit rows.
7. Label from paired final-money differences only: `+1` above $250 without safety regression, `-1` below -$250 or with a safety failure, and `0` otherwise.

Every causal row records the selected replay checkpoint, family, split, proposal evidence, simulation seed/opponent/player order, intervention audit, paired money, safety metrics, label, and acceptance status.

Compute weights with equal target mass per strategy family and a 2:1 win/loss mass inside each family. Normalize accepted-row mean to 1.0 and enforce `[0.5, 2.0]` through bounded iterative calibration; fail generation if family equality cannot be achieved within a documented tolerance.

Generate deterministic seed batches until every modeled output has at least 150 accepted examples with at least 40 positive and 40 negative labels, or reaches 2,000 attempted pairs. Unsupported outputs remain unavailable to SVM training.

## Outputs and Validation

Produce three reproducible artifacts:

- Strategy-family and split manifest.
- Observational replay checkpoint/proposal JSONL plus summary.
- Replay-guided counterfactual JSONL plus class, weight, rejection, and provenance summary.

Tests must cover:

- Player-slot and self-play resolution, tuple deduplication, and rejected-corpus exclusion.
- `steps[t-1]` to `steps[t]` alignment and coincident checkpoint reasons.
- Exact feature/schema agreement between replay and simulation extraction.
- Sentinel tests proving opponent-private fields cannot affect features.
- Deterministic fingerprints, family clustering, splits, and absence of family/episode/seed leakage.
- Proposal detection from confirmed state changes, direction inversion, and infeasible-proposal auditing.
- Uniform family sampling, 2:1 win preference, bounded weight calibration, label thresholds, safety overrides, and quota stopping.
- Reproduction from the frozen manifest, corpus-status file, and seed configuration.

## Assumptions

- This phase creates training-ready causal data but does not fit, export, or integrate `LinearSVC` models.
- Only currently accepted replay files participate; retries for unavailable episodes can later append data under a new corpus snapshot.
- Existing random counterfactual datasets remain historical artifacts and are not silently merged with replay-guided rows.
- `main.py` and runtime strategy behavior remain unchanged.
