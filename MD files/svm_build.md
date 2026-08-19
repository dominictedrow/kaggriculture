# Watcher SVM: Model Training, Margin Scaling, Evaluation, Export

## Context

`SVM.md`, `ARCHITECTURE.md` (§14/§15/§17), and `data.md` ("Training, Export,
and Acceptance") already specify a fairly firm design for a "watcher" that
nudges the strategy follower's product choices: one independent `LinearSVC`
per product's increase/avoid decision plus one for competitive expansion,
with decision-margins rescaled to `[-1, 1]`. None of it is built yet —
`ARCHITECTURE.md` states outright there is no ingestion/training pipeline, no
fitted scaler, no trained coefficients, no export code, no live inference.

Dom is designing the **preprocessing pipeline** himself — feature engineering
in `scripts/shared_features.py` (already exists, 129-dim raw feature vector,
no scaling) and the counterfactual dataset generation/labeling in
`scripts/counterfactual_dataset.py` (already exists: `generate_pair`,
`label_delta`'s ±$250 neutral band, `modeled_output_id`'s per-product routing —
but currently has **no train/val/test split logic**). This plan covers only
what he asked for: **the model itself** — fitting, margin-scaling, evaluation/
acceptance-gating, and export — plus the minimal runtime hook needed to make an
exported model actually usable, and tests. It does not touch feature
extraction, dataset generation, labeling, or split assignment — those stay
Dom's.

Two things were verified by reading the actual file (not just the docs) and
corrected from the initial draft:
- `strategy_follower.py`'s docstring runs from line 1 to line 152 (not ~74) —
  the file currently has **zero import statements** (confirmed by grep; the one
  hit was a false positive inside prose). The `# ---- Constants` block starts
  at line 154.
- `watcher_signals` computes `expansion` at line 755 and returns at line 756 —
  the override hook belongs there, not at line ~792 (which is actually inside
  the unrelated `_adaptive_crop_slots` function).

## 0. Input contract (owned by Dom's pipeline — not designed here)

Every row the trainer consumes is one JSONL line matching
`counterfactual_dataset.py`'s existing shape (`schema_hash`, `feature_order`,
`features`, `output_id`, `label`, `accepted`, ...), **plus** fields that don't
exist yet and that Dom's pipeline needs to add (see §6 for exact naming/shape
questions):

- `strategy_family` — string identifying which strategy family generated the
  row (needed for leave-one-family-out reporting and as the natural split key).
- a split assignment per row — inline `split: "train"|"val"|"test"`, or a
  separate family→split manifest (`data.md` names `strategy_families.json`)
  the trainer loads and joins on `strategy_family`.
- `sample_weight` — float, "replay-derived" per `data.md`.

The trainer only ever **consumes** these — it never derives, reshuffles, or
guesses a split.

## 1. New trainer: `scripts/train_watcher.py`

CLI entry point (`argparse`) with a plain `run(...)` function underneath so
tests call it directly, mirroring `counterfactual_dataset.py`'s
`main()`/module-function split. Dev-only imports: `sklearn.svm.LinearSVC`,
`sklearn.preprocessing.StandardScaler`, `numpy`; reuses
`shared_features.FEATURE_ORDER`/`SCHEMA_HASH`.

Constants: `DEFAULT_C_GRID = (0.01, 0.03, 0.1, 0.3, 1.0, 3.0, 10.0)`,
`DEFAULT_MARGIN_PERCENTILE = 95`, `ACCEPT_MIN_BALANCED_ACC = 0.60`,
`ACCEPT_MIN_MARGIN_OVER_MAJORITY = 0.10`.

Implements the 10-step sequence from `ARCHITECTURE.md` §14 as small, testable
functions:

1. `load_rows(paths)` — read JSONL, tag each row with `(source_path, line_no)`.
2. `validate_and_filter(rows)` — reject (collecting *all* reasons, not just the
   first hit): schema-hash mismatch, feature-order mismatch, `accepted=False`,
   missing/wrong-length/non-finite features, invalid label, missing
   `output_id`/`strategy_family`. Returns `(kept, rejected_with_reasons)`.
3. `resolve_splits(rows, families_manifest=None)` — attaches `_split` per row
   (inline field preferred, else manifest lookup); unresolved rows are
   **rejected with a reason**, never defaulted to "train".
4. `group_by_output(rows)` — key by `output_id`.
5. `partition(rows_for_output)` — `{"train": [...], "val": [...], "test": [...]}`
   strictly from stored `_split`. No row-level reshuffling, ever.
6. `binary_only(rows)` — drops neutral (`label == 0`) rows from fit/eval;
   neutral rows still counted in reported class counts.
7. `check_split_adequacy(partitions, min_per_class)` — each split's
   `binary_only()` must contain ≥`min_per_class` of both `-1` and `+1`; on
   failure the whole `output_id` is marked `unavailable` with a reason and
   skipped — never trained on a degenerate split.
8. `to_matrix` / `to_labels` / `to_weights(rows, default=1.0)` — extraction;
   `to_weights` counts `weight_missing` rows when defaulting.
9. `renormalize_weights(weights)` — rescale to mean 1.0 **over the rows
   passed** (called with train-split rows only) to avoid cross-split leakage
   through weighting. CLI toggle `--reweight-mode {asis,renormalize-train}`
   (default `renormalize-train`).
10. `fit_scaler(X_train)` — `StandardScaler().fit(X_train)`, train split only
    (includes neutral-label train rows — scaling reflects feature
    distribution, not label).
11. `fit_candidates(X, y, weights, c_grid)` — one
    `LinearSVC(C=c, class_weight="balanced", max_iter=5000, random_state=0)
    .fit(X, y, sample_weight=weights)` per grid value.
12. `balanced_accuracy(...)`, `majority_baseline(...)` — thin wrappers;
    `majority_baseline` is the raw majority-class proportion (see §6.4 for why
    balanced-accuracy-of-majority-predictor is the wrong baseline).
13. `select_model(candidates, X_val, y_val, val_weights)` — max **unweighted**
    val balanced accuracy; ties broken by smallest `C`.
14. `margin_scale(model, X_train, percentile)` —
    `max(1e-6, percentile(|decision_function(X_train)|, percentile))`.
15. `pure_score(features, mean, scale, coef, intercept, margin_scale)` — the
    exact pure-Python formula that gets templated into the export module;
    unit-tested against sklearn's own `decision_function` before it's ever
    stringified.
16. `evaluate_split(model, scaler, margin_scale, rows)` — called once, only on
    test: weighted + unweighted balanced accuracy, confusion matrix, class
    counts, weighted + unweighted majority baseline.
17. `leave_one_family_out(train_rows, val_rows, c)` — pool = train+val only
    (test rows structurally cannot be passed in); refit per held-out family,
    evaluate on that family's rows, skip families below `min_per_class`.
18. `gate(test_metrics)` — `accepted = balanced_acc_unweighted >= 0.60 and
    (balanced_acc_unweighted - majority_baseline_unweighted) >= 0.10` — both
    comparisons boundary-inclusive.
19. `export_record(...)` — asserts `tuple(model.classes_) == (-1, 1)` before
    building the plain-data record.
20. `render_module(records, metadata)` — generates `watcher_model.py` source.
21. `render_report(results, metadata)` — JSON + Markdown report text.
22. `run(rows_paths, families_path, output_path, report_path, c_grid,
    margin_percentile, min_per_class, reweight_mode)` — orchestrates 1–10
    across every `output_id`, returns the report dict.
23. `main(argv=None)` — argparse wiring, one-line summary printed at the end.

## 2. Export artifact: `scripts/watcher_model.py`

Auto-generated/overwritable. **Zero sklearn/numpy imports — `math` only**,
enforcing the "Kaggle inference must not import scikit-learn" requirement
structurally:

```python
"""Auto-generated by scripts/train_watcher.py -- do not hand-edit."""
import math

SCHEMA_VERSION = "counterfactual-v1"
SCHEMA_HASH = "<64-hex>"          # must equal shared_features.SCHEMA_HASH
FEATURE_ORDER = (<129 names>,)    # must equal shared_features.FEATURE_ORDER
GENERATED_AT = "..."
DATASET_SNAPSHOT = {"row_files": [...], "row_file_hashes": {...}, "families_manifest": ...}

MODELS = {
    "product:WHEAT:increase": {
        "scaler_mean": (...,), "scaler_scale": (...,),
        "coef": (...,), "intercept": <float>,
        "margin_scale": <float>, "C": <float>, "class_order": (-1, 1),
        "val_balanced_accuracy_unweighted": <float>,
        "test_balanced_accuracy_unweighted": <float>,
        "test_majority_baseline_unweighted": <float>,
        "train_rows": <int>, "val_rows": <int>, "test_rows": <int>,
    },
    # only accepted output_ids are present; rejected/unavailable ones are
    # simply absent, so MODELS.get(output_id) is None and callers fall back.
}

def score(output_id, features):
    """Pure-python decision score in [-1.0, 1.0], or None if unavailable/invalid."""
    entry = MODELS.get(output_id)
    if entry is None or len(features) != len(entry["coef"]):
        return None
    total = entry["intercept"]
    for x, m, s, c in zip(features, entry["scaler_mean"], entry["scaler_scale"], entry["coef"]):
        if not math.isfinite(x):
            return None
        total += ((x - m) / s) * c
    if not math.isfinite(total):
        return None
    return max(-1.0, min(1.0, total / entry["margin_scale"]))
```

`scaler_scale` values are guaranteed non-zero (`StandardScaler` replaces
zero-variance columns' scale with `1.0` internally). `score()` is the single
source of truth used both by the round-trip test and the runtime hook below.

## 3. Training report

`watcher_training_report.json` + `.md` (default location at repo root, next to
the existing `counterfactual_*.summary.json` convention): per-`output_id`
status (`accepted`/`rejected`/`unavailable` + reason), split sizes/class
counts, chosen `C`, per-C validation metrics, val/test balanced accuracy vs.
majority baseline, leave-one-family-out results, `weight_missing` counts — for
Dom to review before touching runtime integration or the A/B promotion harness.

## 4. Runtime integration: `scripts/strategy_follower.py`

Three scoped edits, nothing else in this 1270-line file changes:

1. **Guarded import block right after the docstring closes at line 152**,
   before `# ---- Constants` at line 154:
   ```python
   import math

   try:
       import shared_features
       import watcher_model
   except ImportError:
       shared_features = None
       watcher_model = None
   ```
2. **Delete lines 667-668** (`if backend == "linear_svm": backend = "rules"`)
   — this is the exact unconditional coercion currently forcing every
   `linear_svm` request back to rules. Line 665-666's guard against unknown
   backend strings stays as-is.
3. **Insert the override between the existing `expansion = max(-1.0, min(1.0,
   ...))` line (755) and the `return {` (756)**:
   ```python
   if backend == "linear_svm":
       attractiveness, expansion, backend = _svm_override(attractiveness, expansion, obs, backend)
   ```
   This reassigns the local `backend` variable so the function's existing
   return-dict expression at line 769 (`"backend": backend if
   requested_backend != "off" else "off"`) correctly reports `"linear_svm"` or
   the fallback `"rules"` post-override.
4. **New helper directly above `watcher_signals` (before line 657)**:
   ```python
   def _svm_override(rule_attractiveness, rule_expansion, obs, backend):
       """Overrides product_attractiveness/competitive_expansion_pressure with the
       exported linear_svm model where available; falls back per-signal to the
       rule-computed value on missing module, schema mismatch, or non-finite output."""
       if shared_features is None or watcher_model is None:
           return rule_attractiveness, rule_expansion, "rules"
       if getattr(watcher_model, "SCHEMA_HASH", None) != shared_features.SCHEMA_HASH:
           return rule_attractiveness, rule_expansion, "rules"
       try:
           features = shared_features.extract_features(obs)
       except Exception:
           return rule_attractiveness, rule_expansion, "rules"
       attractiveness = dict(rule_attractiveness)
       for product in attractiveness:
           inc = watcher_model.score(f"product:{product}:increase", features)
           avoid = watcher_model.score(f"product:{product}:avoid", features)
           if inc is not None or avoid is not None:
               attractiveness[product] = max(-1.0, min(1.0, (inc or 0.0) - (avoid or 0.0)))
       exp = watcher_model.score("competitive_expansion", features)
       expansion = rule_expansion if exp is None else exp
       return attractiveness, expansion, "linear_svm"
   ```

Verified: `strategy_follower._PRODUCTS` (`tuple(_BASE_PRICE)`, line 201) is
exactly `shared_features.PRODUCTS` (WHEAT/CARROT/TOMATO/STRAWBERRY/MELON/EGG/
MILK/WOOL), and `counterfactual_dataset.modeled_output_id` already emits keys
in exactly the `product:{item}:increase` / `product:{item}:avoid` shape this
hook queries — the naming lines up with no translation layer needed.

`main.py` is not touched (explicit in both `SVM.md` and `data.md`); the actual
A/B promotion testing via `harness.py` is a separate, later phase.

## 5. Tests: `scripts/test_train_watcher.py`

Plain `unittest.TestCase` + hand-built fixtures, matching
`test_counterfactual_dataset.py`'s existing style (no pytest, no mocking
framework):

- schema validation rejects mismatched hash / wrong feature order / non-finite
  features / unaccepted rows
- split missing is rejected, never defaulted to "train"
- partition never reshuffles rows across splits regardless of input order
- per-split class-requirement check marks a degenerate output `unavailable`
  before it ever reaches `fit_candidates`
- scaler fit uses train rows only (val/test given a deliberately different
  distribution; assert scaler mean/scale match a manual train-only computation)
- margin-scale computation and `pure_score` clipping at exactly ±1.0
- acceptance gate boundary-inclusive at exactly 0.60 and exactly majority+0.10;
  rejects just below each independently
- export round-trip: fit a toy `LinearSVC`, build an `export_record`, assert
  `pure_score` matches `model.decision_function` (scaled + clipped) within
  float tolerance on held-out rows
- missing `sample_weight` defaults to 1.0 and increments a `weight_missing`
  counter, doesn't hard-reject
- output-id grouping matches `counterfactual_dataset.modeled_output_id`'s
  actual routing (reuse its fixtures as ground truth)
- leave-one-family-out structurally cannot see test-split rows
- generated module source has no `import sklearn`/`import numpy` (AST-scan)

## 6. Open parameters needing Dom's decision before/at implementation

1. **C candidate grid** — proposed `(0.01, 0.03, 0.1, 0.3, 1.0, 3.0, 10.0)`,
   selected by unweighted val balanced accuracy, ties to smallest `C`. No doc
   specifies this.
2. **Margin-scale formula** — proposed: 95th percentile of
   `|decision_function(X_train)|`, floored at `1e-6`, final score clipped to
   `[-1,1]`. `SVM.md` doesn't give an exact formula.
3. **Preprocessing-pipeline field names/shapes** (Dom builds these, but the
   trainer needs to agree on the contract): `strategy_family` per row; split
   via inline `split` field vs. a `strategy_families.json` manifest
   (`data.md` §12 names the latter); exact `sample_weight` field name/range
   and whether `renormalize_weights` (train-only mean-1.0 rescale) is wanted.
4. **Accept-gate baseline metric** — recommend gating on unweighted balanced
   accuracy vs. the **raw majority-class proportion** (not 0.5 — balanced
   accuracy of a constant-majority predictor is trivially always 0.5, so it's
   not a meaningful baseline). Weighted variants reported alongside for
   context only.
5. **Increase/avoid combination rule** — `output_id` splits each product into
   two independent classifiers, but the runtime contract exposes one
   `product_attractiveness[product]` scalar. Proposed default:
   `clip(increase_score - avoid_score, -1, 1)`, degrading gracefully to
   whichever single classifier exported. Not specified in any doc.
6. **Fallback granularity** — proposed default is **per-signal** fallback
   (each product independently uses its SVM score if available, else its rule
   value; `backend` reports `"linear_svm"` whenever the schema/module guard
   passes even if some individual products fall back). `SVM.md`'s "non-finite
   model output falls back to rules" doesn't disambiguate per-signal vs.
   whole-backend — flagging for Dom to confirm or override toward stricter
   whole-backend fallback.
7. **`min_per_class`** — the trainer's own defensive per-split floor,
   proposed `1` (bare non-degeneracy), distinct from `SVM.md`'s
   dataset-generation-time ≥40/±40 target quota.

**Dev dependency note:** no `scikit-learn`/`numpy` currently installed in this
environment, no `requirements*.txt` in the repo. Training venv needs both,
dev-only — never imported by `watcher_model.py` or the `strategy_follower.py`
runtime path.

## Verification

- `python -m unittest scripts/test_train_watcher.py -v` — all new trainer unit
  tests pass, in particular the export round-trip test (pure-Python `score()`
  must match sklearn's `decision_function`-derived score within float
  tolerance) and the no-sklearn-in-generated-module AST scan.
- `python -m unittest scripts/test_shared_features.py scripts/test_counterfactual_dataset.py -v`
  — confirm nothing in the existing suite regresses (trainer only reads their
  exports, never modifies them).
- Run `train_watcher.py` against a small real or synthetic counterfactual
  JSONL (with `strategy_family`/split/`sample_weight` fields added per §6.3)
  and inspect `watcher_training_report.md` by hand for at least one accepted
  and one rejected/unavailable `output_id`, to sanity-check the report reads
  correctly before ever wiring runtime integration.
- After runtime integration: `python -m unittest scripts/test_strategy_follower.py`
  if such a suite exists (verify at implementation time), plus manually call
  `strategy_follower.watcher_signals(sample_obs, "linear_svm")` twice — once
  with `watcher_model.py` present and matching schema (expect `backend ==
  "linear_svm"`), once with it deleted/renamed (expect clean fallback to
  `"rules"`, no exception) — before any `harness.py`-based A/B promotion runs.
