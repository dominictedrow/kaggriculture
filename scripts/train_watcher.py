"""Fit, evaluate, gate, and export per-output_id watcher LinearSVC models.

Reads counterfactual_dataset.py-shaped JSONL rows (plus the strategy_family/
split/sample_weight fields owned by Dom's preprocessing pipeline), fits one
LinearSVC per output_id, margin-scales its decision function to [-1, 1], and
exports accepted models as a pure-Python scripts/watcher_model.py -- the only
artifact strategy_follower.py's runtime is allowed to import.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import math
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
from sklearn.metrics import balanced_accuracy_score, confusion_matrix
from sklearn.preprocessing import StandardScaler
from sklearn.svm import LinearSVC

import shared_features


DEFAULT_C_GRID = (0.01, 0.03, 0.1, 0.3, 1.0, 3.0, 10.0)
DEFAULT_MARGIN_PERCENTILE = 95
ACCEPT_MIN_BALANCED_ACC = 0.60
ACCEPT_MIN_MARGIN_OVER_MAJORITY = 0.10
_GATE_EPSILON = 1e-9

# Exact source templated into scripts/watcher_model.py -- pure_score() below
# must stay numerically identical to this, and the export round-trip test
# checks that against sklearn's own decision_function.
_SCORE_FUNCTION_SOURCE = '''def score(output_id, features):
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
'''


def load_rows(paths):
    """Read JSONL rows from every path, tagging each with its source location."""
    rows = []
    for path in paths:
        path = Path(path)
        with path.open("r", encoding="utf-8") as fh:
            for line_no, line in enumerate(fh, start=1):
                line = line.strip()
                if not line:
                    continue
                row = json.loads(line)
                row["_source_path"] = str(path)
                row["_line_no"] = line_no
                rows.append(row)
    return rows


def _reject(row, reasons):
    return {"source_path": row.get("_source_path"), "line_no": row.get("_line_no"), "reasons": reasons}


def validate_and_filter(rows):
    """Split rows into (kept, rejected), collecting every rejection reason per row."""
    kept, rejected = [], []
    for row in rows:
        reasons = []
        if row.get("schema_hash") != shared_features.SCHEMA_HASH:
            reasons.append("schema_hash_mismatch")
        if row.get("feature_order") != list(shared_features.FEATURE_ORDER):
            reasons.append("feature_order_mismatch")
        if row.get("accepted") is not True:
            reasons.append("not_accepted")
        features = row.get("features")
        if (features is None or len(features) != len(shared_features.FEATURE_ORDER) or
                not all(isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)
                        for x in features)):
            reasons.append("invalid_features")
        if row.get("label") not in (-1, 0, 1):
            reasons.append("invalid_label")
        if not row.get("output_id"):
            reasons.append("missing_output_id")
        if not row.get("strategy_family"):
            reasons.append("missing_strategy_family")
        if reasons:
            rejected.append(_reject(row, reasons))
        else:
            kept.append(row)
    return kept, rejected


def resolve_splits(rows, families_manifest=None):
    """Attach `_split` per row from the inline field, else the family manifest; never default."""
    kept, rejected = [], []
    for row in rows:
        split = row.get("split")
        if split not in ("train", "val", "test") and families_manifest is not None:
            split = families_manifest.get(row.get("strategy_family"))
        if split not in ("train", "val", "test"):
            rejected.append(_reject(row, ["split_unresolved"]))
            continue
        resolved = dict(row)
        resolved["_split"] = split
        kept.append(resolved)
    return kept, rejected


def group_by_output(rows):
    grouped = defaultdict(list)
    for row in rows:
        grouped[row["output_id"]].append(row)
    return dict(grouped)


def partition(rows_for_output):
    """{"train": [...], "val": [...], "test": [...]} strictly from stored `_split`."""
    result = {"train": [], "val": [], "test": []}
    for row in rows_for_output:
        split = row["_split"]
        if split not in result:
            raise ValueError(f"unexpected split {split!r} for output_id {row.get('output_id')!r}")
        result[split].append(row)
    return result


def binary_only(rows):
    return [row for row in rows if row["label"] != 0]


def check_split_adequacy(partitions, min_per_class):
    """Each split's binary_only() must have >= min_per_class of both classes, or it's degenerate."""
    for name in ("train", "val", "test"):
        counts = Counter(row["label"] for row in binary_only(partitions[name]))
        if counts[-1] < min_per_class or counts[1] < min_per_class:
            return False, f"{name}_insufficient_class_counts"
    return True, None


def to_matrix(rows):
    return [list(row["features"]) for row in rows]


def to_labels(rows):
    return [int(row["label"]) for row in rows]


def to_weights(rows, default=1.0):
    """Extract sample_weight per row; missing/non-finite weights fall back to `default`."""
    weights, missing = [], 0
    for row in rows:
        weight = row.get("sample_weight")
        if (weight is None or isinstance(weight, bool) or
                not isinstance(weight, (int, float)) or not math.isfinite(weight) or weight <= 0):
            weights.append(default)
            missing += 1
        else:
            weights.append(float(weight))
    return weights, missing


def renormalize_weights(weights):
    """Rescale weights to mean 1.0 over the rows passed -- call with train-split rows only."""
    if not weights:
        return list(weights)
    mean = sum(weights) / len(weights)
    if mean <= 0:
        return list(weights)
    return [w / mean for w in weights]


def fit_scaler(X_train):
    return StandardScaler().fit(np.asarray(X_train, dtype=float))


def fit_candidates(X, y, weights, c_grid):
    """One LinearSVC per C in c_grid, keyed by C (dict preserves c_grid's order)."""
    candidates = {}
    for c in c_grid:
        model = LinearSVC(C=c, class_weight="balanced", max_iter=5000, random_state=0)
        model.fit(X, y, sample_weight=weights)
        candidates[c] = model
    return candidates


def balanced_accuracy(y_true, y_pred, weights=None):
    return float(balanced_accuracy_score(y_true, y_pred, sample_weight=weights))


def majority_baseline(y_true, weights=None):
    """Raw majority-class proportion -- NOT balanced accuracy of a majority predictor (always 0.5)."""
    y_true = list(y_true)
    if weights is None:
        weights = [1.0] * len(y_true)
    totals = {}
    for label, w in zip(y_true, weights):
        totals[label] = totals.get(label, 0.0) + w
    total_weight = sum(weights)
    return max(totals.values()) / total_weight if total_weight else 0.0


def select_model(candidates, X_val, y_val, val_weights=None):
    """Max unweighted val balanced accuracy; ties keep the earliest (smallest C) candidate."""
    best = None
    per_c_metrics = {}
    for c, model in candidates.items():
        pred = model.predict(X_val)
        unweighted = balanced_accuracy(y_val, pred)
        metrics = {"val_balanced_accuracy_unweighted": unweighted}
        if val_weights is not None:
            metrics["val_balanced_accuracy_weighted"] = balanced_accuracy(y_val, pred, val_weights)
        per_c_metrics[c] = metrics
        if best is None or unweighted > best[2]:
            best = (c, model, unweighted)
    return best[0], best[1], per_c_metrics


def margin_scale(model, X_train_scaled, percentile):
    decision = np.abs(model.decision_function(np.asarray(X_train_scaled, dtype=float)))
    return max(1e-6, float(np.percentile(decision, percentile)))


def pure_score(features, mean, scale, coef, intercept, margin_scale_value):
    """Exact formula templated into watcher_model.py's score(); tested against decision_function."""
    total = intercept
    for x, m, s, c in zip(features, mean, scale, coef):
        if not math.isfinite(x):
            return None
        total += ((x - m) / s) * c
    if not math.isfinite(total):
        return None
    return max(-1.0, min(1.0, total / margin_scale_value))


def evaluate_split(model, scaler, margin_scale_value, rows):
    """Called once, only on test: weighted + unweighted metrics, confusion matrix, class counts."""
    class_counts = Counter(row["label"] for row in rows)
    binary = binary_only(rows)
    result = {"class_counts": dict(class_counts), "n_rows": len(rows), "n_binary_rows": len(binary)}
    if not binary:
        return result
    X = scaler.transform(to_matrix(binary))
    y = to_labels(binary)
    weights, weight_missing = to_weights(binary)
    pred = model.predict(X)
    result.update({
        "weight_missing": weight_missing,
        "balanced_accuracy_unweighted": balanced_accuracy(y, pred),
        "balanced_accuracy_weighted": balanced_accuracy(y, pred, weights),
        "majority_baseline_unweighted": majority_baseline(y),
        "majority_baseline_weighted": majority_baseline(y, weights),
        "confusion_matrix": confusion_matrix(y, pred, labels=[-1, 1]).tolist(),
    })
    return result


def leave_one_family_out(train_rows, val_rows, c, min_per_class):
    """Pool = train+val only; test rows structurally cannot be passed in. Refit per held-out family."""
    pool = list(train_rows) + list(val_rows)
    families = sorted({row["strategy_family"] for row in pool})
    results = {}
    for family in families:
        held_out = [row for row in pool if row["strategy_family"] == family]
        fit_rows = [row for row in pool if row["strategy_family"] != family]
        fit_binary, held_binary = binary_only(fit_rows), binary_only(held_out)
        fit_counts = Counter(row["label"] for row in fit_binary)
        held_counts = Counter(row["label"] for row in held_binary)
        if (fit_counts[-1] < min_per_class or fit_counts[1] < min_per_class or
                held_counts[-1] < min_per_class or held_counts[1] < min_per_class):
            results[family] = {"status": "skipped", "reason": "insufficient_class_counts",
                                "n_held_out": len(held_out)}
            continue
        scaler = fit_scaler(to_matrix(fit_rows))
        X_fit, y_fit = scaler.transform(to_matrix(fit_binary)), to_labels(fit_binary)
        weights_fit, _ = to_weights(fit_binary)
        model = LinearSVC(C=c, class_weight="balanced", max_iter=5000, random_state=0)
        model.fit(X_fit, y_fit, sample_weight=weights_fit)
        X_held, y_held = scaler.transform(to_matrix(held_binary)), to_labels(held_binary)
        pred = model.predict(X_held)
        results[family] = {"status": "evaluated", "n_held_out": len(held_binary),
                            "balanced_accuracy_unweighted": balanced_accuracy(y_held, pred),
                            "class_counts": dict(held_counts)}
    return results


def gate(test_metrics):
    """accepted = bacc >= 0.60 and (bacc - majority_baseline) >= 0.10, both boundary-inclusive."""
    bacc = test_metrics["balanced_accuracy_unweighted"]
    baseline = test_metrics["majority_baseline_unweighted"]
    return (bacc >= ACCEPT_MIN_BALANCED_ACC - _GATE_EPSILON and
            (bacc - baseline) >= ACCEPT_MIN_MARGIN_OVER_MAJORITY - _GATE_EPSILON)


def export_record(output_id, model, scaler, margin_scale_value, c,
                   val_balanced_accuracy_unweighted, test_metrics, split_counts):
    assert tuple(int(x) for x in model.classes_) == (-1, 1), \
        f"unexpected class order for {output_id}: {tuple(model.classes_)}"
    return {
        "scaler_mean": tuple(float(x) for x in scaler.mean_),
        "scaler_scale": tuple(float(x) for x in scaler.scale_),
        "coef": tuple(float(x) for x in model.coef_[0]),
        "intercept": float(model.intercept_[0]),
        "margin_scale": float(margin_scale_value),
        "C": float(c),
        "class_order": (-1, 1),
        "val_balanced_accuracy_unweighted": float(val_balanced_accuracy_unweighted),
        "test_balanced_accuracy_unweighted": float(test_metrics["balanced_accuracy_unweighted"]),
        "test_majority_baseline_unweighted": float(test_metrics["majority_baseline_unweighted"]),
        "train_rows": int(split_counts["train"]),
        "val_rows": int(split_counts["val"]),
        "test_rows": int(split_counts["test"]),
    }


def render_module(records, metadata):
    """Generate watcher_model.py source. Zero sklearn/numpy imports -- math only."""
    parts = [
        '"""Auto-generated by scripts/train_watcher.py -- do not hand-edit."""',
        "import math", "",
        f"SCHEMA_VERSION = {metadata['schema_version']!r}",
        f"SCHEMA_HASH = {metadata['schema_hash']!r}",
        f"FEATURE_ORDER = {tuple(metadata['feature_order'])!r}",
        f"GENERATED_AT = {metadata['generated_at']!r}",
        f"DATASET_SNAPSHOT = {metadata['dataset_snapshot']!r}",
        "", "MODELS = {",
    ]
    for output_id in sorted(records):
        parts.append(f"    {output_id!r}: {records[output_id]!r},")
    parts += ["}", "", "# only accepted output_ids are present; MODELS.get(output_id) is None otherwise.", ""]
    parts.append(_SCORE_FUNCTION_SOURCE.rstrip("\n"))
    return "\n".join(parts) + "\n"


def render_report(results, metadata):
    report = {"metadata": metadata, "outputs": results}
    json_str = json.dumps(report, indent=2, sort_keys=True) + "\n"

    lines = ["# Watcher training report", "",
             f"Generated at: {metadata.get('generated_at')}",
             f"Schema hash: {metadata.get('schema_hash')}",
             f"Rows loaded / kept / rejected: {metadata.get('rows_loaded')} / "
             f"{metadata.get('rows_kept')} / {metadata.get('rows_rejected')}", "",
             "| output_id | status | reason | C | val_bacc | test_bacc | test_majority | accepted |",
             "|---|---|---|---|---|---|---|---|"]
    for output_id in sorted(results):
        r = results[output_id]
        test_metrics = r.get("test_metrics", {})
        lines.append("| {} | {} | {} | {} | {} | {} | {} | {} |".format(
            output_id, r.get("status", ""), r.get("reason", ""), r.get("C", ""),
            r.get("val_balanced_accuracy_unweighted", ""),
            test_metrics.get("balanced_accuracy_unweighted", ""),
            test_metrics.get("majority_baseline_unweighted", ""),
            r.get("accepted", "")))
    return json_str, "\n".join(lines) + "\n"


def _file_hash(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run(rows_paths, families_path=None, output_path=None, report_path=None,
        c_grid=DEFAULT_C_GRID, margin_percentile=DEFAULT_MARGIN_PERCENTILE,
        min_per_class=1, reweight_mode="renormalize-train"):
    rows_paths = [Path(p) for p in rows_paths]
    rows = load_rows(rows_paths)
    kept, rejected = validate_and_filter(rows)

    families_manifest = None
    if families_path is not None:
        raw_manifest = json.loads(Path(families_path).read_text(encoding="utf-8"))
        families = raw_manifest.get("families") if isinstance(raw_manifest, dict) else None
        if isinstance(families, list):
            families_manifest = {
                row.get("family_id", row.get("strategy_family")): row.get("split")
                for row in families
                if row.get("family_id", row.get("strategy_family"))
            }
        elif isinstance(raw_manifest.get("family_splits") if isinstance(raw_manifest, dict) else None, dict):
            families_manifest = raw_manifest["family_splits"]
        else:
            families_manifest = raw_manifest
    kept, split_rejected = resolve_splits(kept, families_manifest)
    rejected = rejected + split_rejected

    by_output = group_by_output(kept)
    results, records = {}, {}
    for output_id in sorted(by_output):
        output_rows = by_output[output_id]
        partitions = partition(output_rows)
        split_counts = {name: len(rs) for name, rs in partitions.items()}
        ok, reason = check_split_adequacy(partitions, min_per_class)
        if not ok:
            results[output_id] = {"status": "unavailable", "reason": reason, "split_counts": split_counts}
            continue

        train_rows, val_rows, test_rows = partitions["train"], partitions["val"], partitions["test"]
        train_binary, val_binary = binary_only(train_rows), binary_only(val_rows)

        scaler = fit_scaler(to_matrix(train_rows))
        X_train_full_scaled = scaler.transform(to_matrix(train_rows))
        X_train, y_train = scaler.transform(to_matrix(train_binary)), to_labels(train_binary)
        weights_train, weight_missing_train = to_weights(train_binary)
        if reweight_mode == "renormalize-train":
            weights_train = renormalize_weights(weights_train)
        X_val, y_val = scaler.transform(to_matrix(val_binary)), to_labels(val_binary)
        val_weights, _ = to_weights(val_binary)

        candidates = fit_candidates(X_train, y_train, weights_train, c_grid)
        best_c, best_model, per_c_metrics = select_model(candidates, X_val, y_val, val_weights)
        margin = margin_scale(best_model, X_train_full_scaled, margin_percentile)
        test_metrics = evaluate_split(best_model, scaler, margin, test_rows)
        accepted = gate(test_metrics)
        lofo = leave_one_family_out(train_rows, val_rows, best_c, min_per_class)

        result = {
            "status": "accepted" if accepted else "rejected",
            "C": best_c,
            "per_c_val_metrics": per_c_metrics,
            "val_balanced_accuracy_unweighted": per_c_metrics[best_c]["val_balanced_accuracy_unweighted"],
            "test_metrics": test_metrics,
            "split_counts": split_counts,
            "weight_missing_train": weight_missing_train,
            "leave_one_family_out": lofo,
            "accepted": accepted,
        }
        results[output_id] = result
        if accepted:
            records[output_id] = export_record(
                output_id, best_model, scaler, margin, best_c,
                result["val_balanced_accuracy_unweighted"], test_metrics, split_counts)

    rejection_counts = Counter(reason for entry in rejected for reason in entry["reasons"])
    metadata = {
        "schema_version": shared_features.SCHEMA_VERSION,
        "schema_hash": shared_features.SCHEMA_HASH,
        "feature_order": list(shared_features.FEATURE_ORDER),
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "dataset_snapshot": {
            "row_files": [str(p) for p in rows_paths],
            "row_file_hashes": {str(p): _file_hash(p) for p in rows_paths},
            "families_manifest": str(families_path) if families_path else None,
        },
        "reweight_mode": reweight_mode,
        "c_grid": list(c_grid),
        "margin_percentile": margin_percentile,
        "min_per_class": min_per_class,
        "rows_loaded": len(rows),
        "rows_kept": len(kept),
        "rows_rejected": len(rejected),
        "rejection_reason_counts": dict(rejection_counts),
    }

    if output_path is not None:
        Path(output_path).write_text(render_module(records, metadata), encoding="utf-8")

    report = {"metadata": metadata, "outputs": results}
    if report_path is not None:
        report_path = Path(report_path)
        json_str, md_str = render_report(results, metadata)
        report_path.with_suffix(".json").write_text(json_str, encoding="utf-8")
        report_path.with_suffix(".md").write_text(md_str, encoding="utf-8")
    return report


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--rows", nargs="+", required=True, type=Path)
    p.add_argument("--families", type=Path, default=None)
    p.add_argument("--output", type=Path, default=Path("scripts/watcher_model.py"))
    p.add_argument("--report", type=Path, default=Path("watcher_training_report"))
    p.add_argument("--c-grid", nargs="+", type=float, default=list(DEFAULT_C_GRID))
    p.add_argument("--margin-percentile", type=float, default=DEFAULT_MARGIN_PERCENTILE)
    p.add_argument("--min-per-class", type=int, default=1)
    p.add_argument("--reweight-mode", choices=("asis", "renormalize-train"), default="renormalize-train")
    args = p.parse_args(argv)
    report = run(args.rows, args.families, args.output, args.report,
                 tuple(args.c_grid), args.margin_percentile, args.min_per_class, args.reweight_mode)
    accepted = sum(1 for r in report["outputs"].values() if r.get("status") == "accepted")
    print(f"trained {len(report['outputs'])} output_ids ({accepted} accepted) -> {args.output}")


if __name__ == "__main__":
    main()
