# Preparing the watcher data for SVM training

## Current state

The current local counterfactual dataset is structurally valid but is not yet
ready for `LinearSVC` training.

- 300 attempted pairs produced 205 accepted rows.
- Accepted labels contain 71 negative, 107 neutral, and 27 positive examples.
- All accepted rows have the expected 129-feature order, matching schema hash,
  and finite feature values.
- None of the accepted rows currently contains `strategy_family`, `split`, or
  `sample_weight`.
- No modeled output meets the required per-output class quotas.

Generated datasets live under `data/` and are excluded from Git. The current
full dataset is `data/counterfactual_dataset.jsonl`.

## Readiness process

### 1. Add provenance and weighting fields

Every accepted row supplied to `scripts/train_watcher.py` must contain:

- `strategy_family`: the focal strategy family that produced the state;
- `split`: exactly `train`, `val`, or `test`;
- `sample_weight`: a finite positive number using the documented replay or
  family-weighting policy.

The trainer rejects rows without `strategy_family` or a resolvable split.
Although a missing weight currently defaults to `1.0`, training data should
carry explicit weights so the weighting policy is auditable.

### 2. Split by seed group

Assign the split deterministically from `seed_group`. Every checkpoint or row
derived from the same simulation seed must remain in the same split. Never
split individual rows from one seed across train, validation, and test.

A 70/15/15 or 60/20/20 allocation is acceptable if chosen before model
selection and applied consistently. `strategy_family` remains a separate field
for leave-one-family-out evaluation; it must not replace seed-group isolation.

### 3. Generate adequate signed class coverage

For every modeled output, continue deterministic generation until it has:

- at least 150 accepted examples;
- at least 40 positive labels;
- at least 40 negative labels.

Stop after 2,000 attempted pairs for an output if these requirements remain
unavailable. Leave unsupported outputs on the deterministic rules backend.
Neutral rows may be used when fitting the feature scaler, but they are excluded
from binary SVM fitting and evaluation.

### 4. Improve intervention feasibility

The current run rejected 95 of 300 pairs as unapplied or infeasible. Schedule
each deviation only at checkpoints where it can take effect:

- crop changes require an applicable future crop slot;
- animal changes require a valid purchase or defer opportunity;
- hand changes require a valid hire/removal opportunity;
- land changes require an actionable purchase checkpoint;
- premium-product exits require current or planned exposure.

Track acceptance and signed-label counts per `output_id` after every batch.
Prefer targeted generation for deficient outputs rather than continuing a
uniform random mixture.

### 5. Verify every split is usable

After neutral labels are removed, every trained output must have both positive
and negative examples in train, validation, and test. Set
`--min-per-class` to a meaningful value for the final corpus; the trainer's
default of `1` is only suitable for smoke tests.

Before fitting, validate:

- schema version and schema hash;
- exact feature order and 129-value feature length;
- finite feature values and positive finite weights;
- labels restricted to `-1`, `0`, and `1`;
- accepted causal pairs only;
- seed groups isolated to one split;
- required class counts for each output and split.

### 6. Install development-only dependencies

The training environment needs Python 3.11 with:

- `numpy`;
- `scikit-learn`;
- `kaggle-environments` for dataset generation and related tests.

These libraries are development dependencies. The exported Kaggle inference
artifact must remain pure Python and must not import NumPy or scikit-learn.

### 7. Fit without leakage

For each eligible `output_id`:

1. Fit `StandardScaler` using training rows only.
2. Fit candidate `LinearSVC` models on non-neutral training rows.
3. Select `C` using validation balanced accuracy, breaking ties with the
   smaller `C`.
4. Calculate the margin scale from training decision margins only.
5. Evaluate exactly once on the untouched test split.
6. Run leave-one-strategy-family-out diagnostics using train and validation
   rows only.

Weights may be renormalized to mean `1.0` over training rows. Never calculate
scaling, weights, hyperparameters, or thresholds from test outcomes.

### 8. Apply the model acceptance gate

An output is exportable only when its untouched-test performance satisfies
both conditions:

- balanced accuracy is at least `0.60`;
- balanced accuracy is at least `0.10` above the majority baseline.

Review the generated JSON and Markdown reports before runtime evaluation.
Rejected or unavailable outputs must remain absent from the exported model so
runtime inference falls back to deterministic rules.

### 9. Export and validate runtime behavior

Export accepted scaler parameters, coefficients, intercepts, feature order,
schema hash, and margin scales to `scripts/watcher_model.py`. Verify that:

- pure-Python scores match scikit-learn decision scores;
- all scores are finite and clipped to `[-1, 1]`;
- schema mismatch, malformed features, missing outputs, and non-finite values
  fall back safely;
- Kaggle runtime code imports neither NumPy nor scikit-learn.

### 10. Run gameplay acceptance testing

After offline acceptance, compare the SVM watcher against the preceding rules
watcher with paired seeds and alternating player order. Promote it only if the
project's paired-money, safety, regression, and operational gates pass.

## Expected commands

Generate local data directly under the ignored data directory:

```bash
PYTHONPATH=scripts python scripts/counterfactual_dataset.py \
  --output data/counterfactual_dataset.jsonl \
  --pairs <batch-size> \
  --seed-base <first-seed>
```

After preprocessing adds provenance, seed-safe splits, and weights, train with:

```bash
PYTHONPATH=scripts python scripts/train_watcher.py \
  --rows data/counterfactual_dataset.jsonl \
  --output scripts/watcher_model.py \
  --report watcher_training_report \
  --min-per-class <final-threshold>
```

Do not commit JSONL datasets, replay caches, generated reports, fitted model
artifacts that have not passed acceptance, or local virtual environments.
