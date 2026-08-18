# SVM Architecture

## Status at a glance

The repository currently contains the data-generation side of a proposed linear-SVM watcher and a deterministic rules-based watcher at runtime. It does **not** yet contain an SVM ingestion/training pipeline, a fitted scaler, trained model coefficients, model export code, or live SVM inference.

The implemented path is:

```text
accepted Kaggle replays
        |
        v
causally aligned replay checkpoints
        |
        +--> fixed observational feature vectors
        |
        v
confirmed expert proposals
        |
        v
strategy-family 60/20/20 split
        |
        v
paired local counterfactual simulations
        |
        v
accepted causal labels, safety audits, and weights
```

The intended but not yet implemented continuation is:

```text
aligned causal features + labels
        |
        v
train-only preprocessing and weighting
        |
        v
one LinearSVC per supported output
        |
        v
validation/model selection, then final test
        |
        v
self-contained exported coefficients
        |
        v
runtime watcher inference
```

At runtime, `strategy_follower.py` presently implements only the deterministic watcher. Asking for the `linear_svm` backend deliberately falls back to `rules` because no model has been exported.

## Architectural goal

The SVM is designed as a bounded advisory layer, not as the farm controller. The existing strategy follower remains responsible for routing, deadlines, purchases, planting, livestock care, cash constraints, and endgame behavior. A future model would modify a small set of high-level watcher signals:

- product attractiveness for each crop or animal product;
- whether a product should be increased or avoided;
- competitive expansion pressure affecting labor and land decisions;
- recommended exposure limits, subject to deterministic clamps.

This makes the architecture hybrid. Learned scores can influence adaptive targets, but deterministic capacity, payback, land, cash-reserve, and lifecycle rules remain authoritative.

## 1. Replay corpus and trajectory selection

The observational pipeline begins in `kaggle_replays/replay_training.py`.

`accepted_trajectories()` resolves each focal leaderboard trajectory as a tuple of:

```text
(episode_id, player_slot, submission_id)
```

Using the player slot is important because both players may be relevant in genuine self-play. Tuple-level deduplication preserves both slots while avoiding duplicate references to the same focal trajectory. Replays that are unavailable, rejected by corpus auditing, or associated with the wrong team/submission are not silently admitted.

The selected corpus is frozen through manifest and corpus-status metadata. Generated summaries retain hashes and counts so a dataset can be tied back to its exact replay cohort.

## 2. Causal action/state alignment

Kaggle replay actions and observations are offset by one replay step. For an action stored at `steps[t].action`, the source state is the observation at `steps[t - 1].observation`.

`iter_rows_for_trajectory()` preserves that alignment and emits checkpoints at:

- the start of a game day; and
- the observation where a new town shop becomes visible.

If both events occur together, both checkpoint reasons are retained. Actions between the current checkpoint and the next checkpoint are then examined against the later observable state.

This stage uses replay outcomes only as proposal-sampling context. Replay wins, losses, final money, and margins are recorded for provenance, but they are not used as SVM `+1/-1` labels.

## 3. Shared feature schema

`shared_features.py` defines the single fixed feature order and schema hash used by replay observations and the historical counterfactual generator. `extract_features()` produces raw aggregate features in the following groups.

### Time and phase

- turn, day, and hour;
- fraction of the season remaining;
- opening, midgame, and endgame indicators.

### Public farm state for both players

- money, active hands, and unlocked quadrants;
- weeds, empty tiles, and ready yield;
- feed-risk and water-risk counts;
- coop and pasture counts;
- goose, cow, and sheep counts;
- crop counts for wheat, carrot, tomato, strawberry, and melon;
- crop-age buckets of 0–2, 3–7, and 8+ days.

### Focal-player private state

- shed inventory by product, animal, and fertilizer;
- carried inventory across the farmer and hands;
- seed inventory for each crop.

Only the focal observation's `private` field is read. Opponent-private inventory is neither available nor included. Opponent farm tiles and money are public game state and are therefore legitimate runtime features.

### Shared market and town state

- count of each unlocked shop type;
- current price divided by base price for every saleable product;
- market-inventory displacement normalized by product throughput.

### Derived workload features

- capacity backlog: feed risk + water risk + ready yield;
- estimated travel: productive assets divided by available units;
- asset-service ratio: assets divided by 24 actions per unit per day.

`FEATURE_ORDER` fixes column order. `SCHEMA_HASH` hashes the version and feature names, allowing ingestion to reject incompatible rows rather than silently misaligning columns.

The vectors are currently raw. The design calls for normalization of naturally bounded counts and a `StandardScaler` for unbounded numeric columns, but that preprocessing has not been implemented. When added, all learned preprocessing parameters must be fitted on the training split only.

## 4. Expert proposal extraction

Replay checkpoints are observational evidence, not causal labels. `confirmed_proposals()` compares the source state, interval actions, and later state to identify concrete strategy changes.

Supported proposal concepts include:

- product increase or avoid;
- product redirection;
- animal add or defer;
- labor add or remove;
- land advance or defer;
- premium-product retain or exit.

A market order alone is insufficient because invalid orders can fail silently in Kaggriculture. A proposal becomes sampleable only when the relevant action and subsequent state change confirm that it was feasible and took effect. Ambiguous proposals remain available as audit records but are not sampled for causal generation.

The observational JSONL therefore contains features and future behavior summaries, but it does not emit causal labels.

## 5. Strategy-family grouping

The split unit is a strategy family, not an individual row or turn.

`trajectory_signature()` fingerprints the early action sequence and later layout checkpoints while normalizing away transient fields. `assign_families()` finds the modal signature for each submission and merges submissions only when their modal signatures match exactly. Low-support or ambiguous submissions remain isolated rather than being forced into another family.

This addresses several leakage modes:

- checkpoints from one episode cannot appear in multiple splits;
- many turns from the same trajectory cannot be divided between train and test;
- submissions implementing the same apparent strategy cannot be scattered across splits merely because their submission IDs differ.

## 6. The 60/20/20 data split

`split_families()` deterministically assigns complete families to these target proportions:

- 60% training;
- 20% validation;
- 20% test.

The assignment minimizes squared distance from the target trajectory counts while keeping each family atomic. Stable family and split ordering makes repeated generation deterministic.

Because the current corpus has only five detected families, exact row percentages are not guaranteed. Family isolation takes precedence over exact percentages. The validation and test cohorts may each contain only one family, which is leakage-safe but makes their estimates sensitive to the behavior of that family.

Some replay episodes contain focal trajectories from two families assigned to different splits. `emission_cohort()` excludes those entire episodes instead of allowing the shared game state to bridge two cohorts.

The generator also checks that replay episode IDs, family IDs, and simulation seeds occur in only one split. The checked-in datasets predate the change to 60/20/20 and retain their old assignments until regenerated.

## 7. Guided proposal sampling

`kaggle_replays/replay_guided.py` flattens each observational checkpoint into one row per proposal and maps proposal spellings onto modeled outputs.

The intended classifiers are:

```text
product:<PRODUCT>:increase
product:<PRODUCT>:avoid
competitive_expansion
```

Products are wheat, carrot, tomato, strawberry, melon, egg, milk, and wool. Labor and land proposals map to `competitive_expansion`.

Sampling cycles uniformly through available strategy families. Within each family it requests winning replay trajectories twice as often as losing trajectories, falling back to the available outcome if one side is absent. Ties are excluded from sampling.

The replay outcome influences which intervention proposal is explored; it still does not determine the causal label.

## 8. Counterfactual simulation

`kaggle_replays/causal_sim.py` converts a sampled proposal into a bounded local intervention and executes a causal triplet:

1. baseline strategy;
2. expert-consistent intervention;
3. bounded opposite intervention.

All branches use the same simulation seed, opponent, player order, and replayed pre-checkpoint action prefix. Local opponents rotate among `starter`, `ring`, and `leader_clone`, while player order alternates.

### Effective checkpoint selection

The replay-requested checkpoint is not always feasible in the local baseline strategy. The simulator may select another feasible day-start or shop-unlock checkpoint within the same broad game phase. Selection examines baseline observations and actions, not intervention rewards.

This is a crucial boundary for future ingestion: the SVM feature vector must describe the **effective simulation checkpoint**, not blindly reuse the feature vector from the requested replay checkpoint. Otherwise the model would be trained on a state different from the one whose intervention produced the label.

### Coupled randomness and prefix equality

The branches preserve and audit:

- checkpoint-state hashes;
- pre-checkpoint action hashes;
- observable RNG-path hashes;
- the exogenous environment table;
- intervention requested/applied counts.

A causal direction is rejected if its baseline and intervention do not share the same checkpoint state, action prefix, or RNG path, or if the intervention is infeasible, partial, absent, or otherwise fails its audit.

## 9. Safety instrumentation and labels

Each baseline/intervention pair records final money and safety metrics:

- feed-risk tile-turns;
- water-risk tile-turns;
- escaped animals;
- missed watering deaths;
- shed-overflow indicators;
- ending saleable inventory;
- invalid/no-op purchase indicators when available;
- market-order-cap violations.

Escaped animals, missed watering deaths, and market-order-cap violations are hard safety gates. If hard-safety instrumentation is unavailable, the row is rejected.

For an accepted direction:

```text
delta = intervention final money - baseline final money

label = +1  when delta > 250 and no hard safety regression
label = -1  when delta < -250 or a hard safety regression occurs
label =  0  otherwise
```

The strict inequalities mean exactly `+250` or `-250` is neutral.

The architecture proposes binary `LinearSVC` models. Neutral rows therefore require an explicit ingestion policy, most naturally exclusion from binary fitting while retaining them for auditing. No such ingestion rule is implemented yet.

## 10. Quotas and availability

Generation proceeds independently by modeled output until it obtains:

- at least 150 accepted rows;
- at least 40 positive labels;
- at least 40 negative labels;

or reaches 2,000 attempted direction pairs. Outputs without proposal evidence, without source coverage in all required splits, or without sufficient feasible signed examples are marked unavailable rather than silently trained with weak data.

Current artifacts support only part of the intended output surface. Competitive expansion, wheat, melon, milk, wool, and strawberry-increase have usable evidence in at least one completed artifact. Egg and tomato lack proposal evidence, strawberry-avoid is infeasible in the current generation, and carrot coverage has varied across generation attempts and splits.

Readiness must ultimately be assessed per output **and per split**. A global quota can say an output is complete even when its training cohort lacks the signed examples needed to fit a model.

## 11. Sample weights

Accepted rows receive weights intended to:

- give each strategy family equal total mass;
- give replay wins twice the mass of replay losses within a family;
- normalize the accepted-row mean weight to 1.0;
- stay within `[0.5, 2.0]`.

The current generator calibrates these weights across all accepted rows after generation. That includes validation and test composition and is therefore not suitable for leakage-free training. The ingestion pipeline must ignore these global weights or recompute them using training rows only. Validation and test metrics should ordinarily use unmodified evaluation weights chosen without observing their labels or distributions.

## 12. Stored artifacts

The main generated artifacts under `kaggle_replays/training_data/` are:

- `strategy_families.json`: selected corpus, trajectory signatures, family IDs, split assignment, and exclusions;
- `expert_proposals.jsonl`: replay checkpoint features, outcomes, confirmed changes, proposals, and sampleability;
- `expert_proposals.summary.json`: cohort and proposal coverage summary;
- `causal_training*.jsonl`: paired causal outcomes, provenance, audit data, labels, and weights;
- matching `.summary.json` files: configuration hashes, quota status, class counts, rejection counts, and source coverage.

Historical files at the repository root, such as `counterfactual_dataset.jsonl`, come from random simulations without the replay-family split architecture. They must not be silently mixed into the replay-guided corpus.

## 13. Current causal-row gap

The observational replay rows contain `features`, but `flatten_observations()` does not carry them into proposal records and `causal_row()` does not emit a feature vector. As a result, the current causal JSONL files contain labels and audit provenance but no trainable `X` matrix.

This omission cannot be repaired safely with a naïve join because the simulator may move to a different effective checkpoint. The correct future design is to extract the shared feature schema directly from the baseline observation at the effective simulation checkpoint and write that vector, feature schema version, and schema hash into each causal row.

## 14. Intended SVM layer

`SVM.md` proposes a compact collection of independent linear classifiers rather than one multiclass model:

- one increase classifier and one avoid classifier for each supported product;
- one competitive-expansion classifier.

The intended appeal of `LinearSVC` is a small, deterministic deployment artifact: after preprocessing, inference is a dot product plus intercept. Coefficients, intercepts, feature order, scaler parameters, schema version, and any score calibration can be embedded directly into the self-contained submission.

The training/evaluation sequence should be:

1. load only causal rows matching the expected causal and feature schema hashes;
2. reject unaccepted, malformed, non-finite, or misaligned rows;
3. group by `output_id`;
4. keep the stored family split and never perform a row-level reshuffle;
5. fit scaling and any resampling/weighting from training rows only;
6. fit candidate `LinearSVC` configurations on training signed labels;
7. use validation families for model and threshold selection;
8. freeze the complete pipeline;
9. evaluate once on the untouched test families;
10. export only models that pass offline and paired-game acceptance gates.

This trainer does not currently exist.

## 15. Runtime watcher integration

`strategy_follower.py` exposes:

```python
WATCHER_BACKEND = "rules"  # "off" | "rules" | "linear_svm"
```

`watcher_signals(obs, backend)` returns:

- product attractiveness;
- town demand pressure;
- opponent supply pressure;
- market glut risk;
- competitive expansion pressure;
- recommended product exposure, hands, quadrants, and cash reserve;
- the effective backend.

The rules implementation uses town demand, public opponent assets, current prices, market inventory, workload, and remaining season economics. These bounded signals feed `_adaptive_targets()`, which modifies crop and animal profitability scores and expansion targets while retaining deterministic clamps.

At present:

```text
requested backend = linear_svm
effective backend = rules
```

There is no feature extraction, scaler application, coefficient lookup, decision-function calculation, or model-schema check in the runtime strategy. `main.py` also does not contain the newer watcher/SVM architecture and remains the current standalone submission artifact.

## 16. Tests and invariants

Existing tests cover important data-generation contracts, including:

- replay action/observation alignment;
- coincident checkpoint reasons;
- tuple deduplication and self-play slots;
- deterministic family-atomic splitting;
- the 60/20/20 target with equal-sized families;
- exclusion of cross-split episodes;
- proposal confirmation from interval actions and state changes;
- label boundaries and safety override behavior;
- quota stopping and unavailable outputs;
- missing source-split handling;
- weight bounds and calibration;
- causal prefix/checkpoint/RNG audit behavior.

The generator's final leakage assertion checks replay episodes, strategy families, and simulation seeds across splits. Future ingestion tests still need to cover train-only preprocessing, exact feature/checkpoint alignment, per-output split adequacy, model serialization equivalence, and runtime schema rejection.

## 17. Readiness summary

Implemented and structurally sound:

- frozen replay provenance;
- causal action/state alignment;
- fixed observation-only feature schema;
- confirmed expert proposal extraction;
- family-atomic 60/20/20 splitting;
- cross-split episode exclusion;
- paired and RNG-coupled counterfactual simulation;
- audited intervention acceptance;
- causal money/safety labels;
- per-output quotas and availability reporting;
- deterministic rules watcher and adaptive-target integration.

Still required before leakage-free SVM training:

- extract features from the effective simulation checkpoint;
- include those features and their schema hash in causal rows;
- implement strict causal-data ingestion and validation;
- recompute sample weights from training rows only;
- define neutral-label handling;
- enforce per-output, per-split signed class requirements;
- implement train-only scaling and `LinearSVC` fitting;
- implement validation selection and untouched test evaluation;
- export scaler/model parameters into a self-contained artifact;
- add real runtime `linear_svm` inference with safe fallback;
- regenerate artifacts using the new 60/20/20 family split.

Until these pieces exist, the repository should be described as having an SVM-oriented causal-data architecture, not a trained or deployed SVM system.
