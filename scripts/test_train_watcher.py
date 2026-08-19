import ast
import random
import unittest

import numpy as np
from sklearn.preprocessing import StandardScaler
from sklearn.svm import LinearSVC

import counterfactual_dataset as cd
import shared_features as sf
import train_watcher as tw


N_FEATURES = len(sf.FEATURE_ORDER)


def make_features(rng, offset=0.0, dim=0):
    vec = [rng.gauss(0.0, 1.0) for _ in range(N_FEATURES)]
    vec[dim] += offset
    return vec


def make_row(rng, label, split, strategy_family="fam_a", output_id="product:WHEAT:increase",
             sample_weight=1.0, accepted=True, schema_hash=None, feature_order=None,
             features=None, offset_dim=0):
    if features is None:
        offset = {1: 3.0, -1: -3.0, 0: 0.0}[label]
        features = make_features(rng, offset, offset_dim)
    row = {
        "schema_version": sf.SCHEMA_VERSION,
        "schema_hash": sf.SCHEMA_HASH if schema_hash is None else schema_hash,
        "feature_order": list(sf.FEATURE_ORDER) if feature_order is None else feature_order,
        "features": features,
        "output_id": output_id,
        "label": label,
        "accepted": accepted,
        "strategy_family": strategy_family,
    }
    if split is not None:
        row["split"] = split
    if sample_weight is not None:
        row["sample_weight"] = sample_weight
    return row


class SchemaValidationTests(unittest.TestCase):
    def test_schema_validation_rejects_bad_rows(self):
        rng = random.Random(0)
        good = make_row(rng, 1, "train")
        bad_hash = make_row(rng, 1, "train", schema_hash="deadbeef")
        bad_order = make_row(rng, 1, "train", feature_order=list(sf.FEATURE_ORDER)[::-1])
        bad_features = make_row(rng, 1, "train")
        bad_features["features"][0] = float("nan")
        unaccepted = make_row(rng, 1, "train", accepted=False)

        kept, rejected = tw.validate_and_filter([good, bad_hash, bad_order, bad_features, unaccepted])

        self.assertEqual(kept, [good])
        reasons_seen = [r["reasons"] for r in rejected]
        self.assertIn(["schema_hash_mismatch"], reasons_seen)
        self.assertIn(["feature_order_mismatch"], reasons_seen)
        self.assertIn(["invalid_features"], reasons_seen)
        self.assertIn(["not_accepted"], reasons_seen)


class SplitResolutionTests(unittest.TestCase):
    def test_split_missing_is_rejected_never_defaulted(self):
        rng = random.Random(1)
        row = make_row(rng, 1, split=None)

        kept, rejected = tw.resolve_splits([row])

        self.assertEqual(kept, [])
        self.assertEqual(rejected[0]["reasons"], ["split_unresolved"])

    def test_split_resolves_via_manifest_when_inline_missing(self):
        rng = random.Random(2)
        row = make_row(rng, 1, split=None, strategy_family="fam_b")

        kept, rejected = tw.resolve_splits([row], families_manifest={"fam_b": "val"})

        self.assertEqual(rejected, [])
        self.assertEqual(kept[0]["_split"], "val")

    def test_inline_split_preferred_over_manifest(self):
        rng = random.Random(3)
        row = make_row(rng, 1, split="test", strategy_family="fam_b")

        kept, rejected = tw.resolve_splits([row], families_manifest={"fam_b": "val"})

        self.assertEqual(rejected, [])
        self.assertEqual(kept[0]["_split"], "test")


class PartitionTests(unittest.TestCase):
    def test_partition_never_reshuffles_rows_across_splits(self):
        rng = random.Random(4)
        rows = [make_row(rng, 1, "test"), make_row(rng, -1, "train"), make_row(rng, 1, "val")]
        for row in rows:
            row["_split"] = row["split"]

        partitions = tw.partition(rows)

        self.assertEqual([r["_split"] for r in partitions["train"]], ["train"])
        self.assertEqual([r["_split"] for r in partitions["val"]], ["val"])
        self.assertEqual([r["_split"] for r in partitions["test"]], ["test"])


class SplitAdequacyTests(unittest.TestCase):
    def test_check_split_adequacy_marks_degenerate_output_unavailable(self):
        rng = random.Random(5)
        partitions = {
            "train": [make_row(rng, 1, "train") for _ in range(3)] + [make_row(rng, -1, "train") for _ in range(3)],
            "val": [make_row(rng, 1, "val")],
            "test": [make_row(rng, 1, "test") for _ in range(3)] + [make_row(rng, -1, "test") for _ in range(3)],
        }

        ok, reason = tw.check_split_adequacy(partitions, min_per_class=2)

        self.assertFalse(ok)
        self.assertEqual(reason, "val_insufficient_class_counts")

    def test_check_split_adequacy_passes_when_all_splits_meet_minimum(self):
        rng = random.Random(6)
        partitions = {name: [make_row(rng, 1, name) for _ in range(2)] + [make_row(rng, -1, name) for _ in range(2)]
                      for name in ("train", "val", "test")}

        ok, reason = tw.check_split_adequacy(partitions, min_per_class=2)

        self.assertTrue(ok)
        self.assertIsNone(reason)


class ScalerTests(unittest.TestCase):
    def test_scaler_fit_uses_train_rows_only(self):
        rng = random.Random(7)
        train_rows = ([make_row(rng, 1, "train", offset_dim=5) for _ in range(4)] +
                      [make_row(rng, -1, "train", offset_dim=5) for _ in range(4)])
        val_rows = [make_row(rng, 1, "val", offset_dim=5) for _ in range(4)]
        for row in val_rows:
            row["features"] = [x + 1000.0 for x in row["features"]]

        X_train = tw.to_matrix(train_rows)
        scaler = tw.fit_scaler(X_train)
        manual = StandardScaler().fit(np.array(X_train, dtype=float))

        np.testing.assert_allclose(scaler.mean_, manual.mean_)
        np.testing.assert_allclose(scaler.scale_, manual.scale_)
        self.assertGreater(abs(scaler.mean_[0] - 1000.0), 500.0)


class MarginScoreTests(unittest.TestCase):
    def test_margin_scale_and_pure_score_clip_at_bounds(self):
        rng = random.Random(8)
        rows = [make_row(rng, 1, "train") for _ in range(20)] + [make_row(rng, -1, "train") for _ in range(20)]
        X = tw.to_matrix(rows)
        scaler = tw.fit_scaler(X)
        X_scaled = scaler.transform(X)
        y = tw.to_labels(rows)
        model = LinearSVC(C=1.0, class_weight="balanced", max_iter=5000, random_state=0)
        model.fit(X_scaled, y)

        margin = tw.margin_scale(model, X_scaled, 95)
        self.assertGreaterEqual(margin, 1e-6)

        mean, scale = tuple(scaler.mean_), tuple(scaler.scale_)
        coef, intercept = tuple(model.coef_[0]), float(model.intercept_[0])
        huge_positive = [x * 1e6 for x in rows[0]["features"]]
        huge_negative = [-x * 1e6 for x in rows[0]["features"]]
        pos_score = tw.pure_score(huge_positive, mean, scale, coef, intercept, margin)
        neg_score = tw.pure_score(huge_negative, mean, scale, coef, intercept, margin)

        self.assertIn(pos_score, (1.0, -1.0))
        self.assertIn(neg_score, (1.0, -1.0))
        self.assertLessEqual(abs(pos_score), 1.0)
        self.assertLessEqual(abs(neg_score), 1.0)

    def test_pure_score_returns_none_for_non_finite_input(self):
        mean = scale = coef = (0.0,) * N_FEATURES
        features = [float("nan")] * N_FEATURES
        self.assertIsNone(tw.pure_score(features, mean, scale, coef, 0.0, 1.0))


class GateTests(unittest.TestCase):
    def test_gate_is_boundary_inclusive(self):
        self.assertTrue(tw.gate({"balanced_accuracy_unweighted": 0.60, "majority_baseline_unweighted": 0.50}))
        self.assertFalse(tw.gate({"balanced_accuracy_unweighted": 0.59, "majority_baseline_unweighted": 0.50}))
        self.assertTrue(tw.gate({"balanced_accuracy_unweighted": 0.70, "majority_baseline_unweighted": 0.60}))
        self.assertFalse(tw.gate({"balanced_accuracy_unweighted": 0.69, "majority_baseline_unweighted": 0.60}))


class ExportRoundTripTests(unittest.TestCase):
    def test_export_round_trip_matches_decision_function(self):
        rng = random.Random(9)
        rows = [make_row(rng, 1, "train", offset_dim=2) for _ in range(20)] + \
               [make_row(rng, -1, "train", offset_dim=2) for _ in range(20)]
        holdout = [make_row(rng, 1, "test", offset_dim=2) for _ in range(5)] + \
                  [make_row(rng, -1, "test", offset_dim=2) for _ in range(5)]

        X = tw.to_matrix(rows)
        scaler = tw.fit_scaler(X)
        X_scaled = scaler.transform(X)
        y = tw.to_labels(rows)
        model = LinearSVC(C=1.0, class_weight="balanced", max_iter=5000, random_state=0)
        model.fit(X_scaled, y)
        margin = tw.margin_scale(model, X_scaled, 95)

        mean, scale = tuple(scaler.mean_), tuple(scaler.scale_)
        coef, intercept = tuple(model.coef_[0]), float(model.intercept_[0])
        X_hold = tw.to_matrix(holdout)
        X_hold_scaled = scaler.transform(X_hold)
        expected = np.clip(model.decision_function(X_hold_scaled) / margin, -1.0, 1.0)

        for feats, exp in zip(X_hold, expected):
            got = tw.pure_score(feats, mean, scale, coef, intercept, margin)
            self.assertAlmostEqual(got, float(exp), places=6)


class WeightTests(unittest.TestCase):
    def test_missing_sample_weight_defaults_to_one_and_counts_missing(self):
        rng = random.Random(10)
        row_with = make_row(rng, 1, "train", sample_weight=2.5)
        row_without = make_row(rng, 1, "train", sample_weight=None)

        weights, missing = tw.to_weights([row_with, row_without])

        self.assertEqual(weights, [2.5, 1.0])
        self.assertEqual(missing, 1)

    def test_renormalize_weights_rescales_to_mean_one(self):
        weights = tw.renormalize_weights([1.0, 2.0, 3.0])
        self.assertAlmostEqual(sum(weights) / len(weights), 1.0)


class OutputGroupingTests(unittest.TestCase):
    def test_output_id_grouping_matches_counterfactual_dataset_routing(self):
        rng = random.Random(11)
        deviation = {"kind": "animal_add_one", "item": "COW"}
        output_id = cd.modeled_output_id(deviation)
        self.assertEqual(output_id, "product:MILK:increase")
        row = make_row(rng, 1, "train", output_id=output_id)

        grouped = tw.group_by_output([row])

        self.assertIn(output_id, grouped)
        self.assertEqual(grouped[output_id], [row])


class LeaveOneFamilyOutTests(unittest.TestCase):
    def test_leave_one_family_out_only_ever_sees_train_and_val_rows(self):
        rng = random.Random(12)
        train_rows = ([make_row(rng, 1, "train", strategy_family="fam_a") for _ in range(5)] +
                      [make_row(rng, -1, "train", strategy_family="fam_a") for _ in range(5)] +
                      [make_row(rng, 1, "train", strategy_family="fam_b") for _ in range(5)] +
                      [make_row(rng, -1, "train", strategy_family="fam_b") for _ in range(5)])
        val_rows = ([make_row(rng, 1, "val", strategy_family="fam_a") for _ in range(3)] +
                    [make_row(rng, -1, "val", strategy_family="fam_a") for _ in range(3)])

        # leave_one_family_out(train_rows, val_rows, c, min_per_class) has no
        # parameter through which test-split rows could reach it at all.
        results = tw.leave_one_family_out(train_rows, val_rows, 1.0, min_per_class=2)

        self.assertEqual(results["fam_a"]["status"], "evaluated")
        self.assertEqual(results["fam_b"]["status"], "evaluated")
        self.assertEqual(results["fam_a"]["n_held_out"], 16)
        self.assertEqual(results["fam_b"]["n_held_out"], 10)

    def test_leave_one_family_out_skips_families_below_min_per_class(self):
        rng = random.Random(13)
        train_rows = ([make_row(rng, 1, "train", strategy_family="fam_a") for _ in range(5)] +
                      [make_row(rng, -1, "train", strategy_family="fam_a") for _ in range(5)] +
                      [make_row(rng, 1, "train", strategy_family="fam_c") for _ in range(1)])

        results = tw.leave_one_family_out(train_rows, [], 1.0, min_per_class=2)

        self.assertEqual(results["fam_c"]["status"], "skipped")


class GeneratedModuleTests(unittest.TestCase):
    def test_generated_module_source_has_no_forbidden_imports_and_round_trips(self):
        rng = random.Random(14)
        rows = [make_row(rng, 1, "train", offset_dim=3) for _ in range(20)] + \
               [make_row(rng, -1, "train", offset_dim=3) for _ in range(20)]
        X = tw.to_matrix(rows)
        scaler = tw.fit_scaler(X)
        X_scaled = scaler.transform(X)
        y = tw.to_labels(rows)
        model = LinearSVC(C=1.0, class_weight="balanced", max_iter=5000, random_state=0)
        model.fit(X_scaled, y)
        margin = tw.margin_scale(model, X_scaled, 95)

        record = tw.export_record(
            "product:WHEAT:increase", model, scaler, margin, 1.0, 0.9,
            {"balanced_accuracy_unweighted": 0.9, "majority_baseline_unweighted": 0.5},
            {"train": 40, "val": 10, "test": 10})
        metadata = {
            "schema_version": sf.SCHEMA_VERSION, "schema_hash": sf.SCHEMA_HASH,
            "feature_order": list(sf.FEATURE_ORDER), "generated_at": "2026-01-01T00:00:00+00:00",
            "dataset_snapshot": {"row_files": [], "row_file_hashes": {}, "families_manifest": None},
        }
        source = tw.render_module({"product:WHEAT:increase": record}, metadata)

        tree = ast.parse(source)
        forbidden = {"numpy", "sklearn"}
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    self.assertNotIn(alias.name.split(".")[0], forbidden)
            elif isinstance(node, ast.ImportFrom):
                self.assertNotIn((node.module or "").split(".")[0], forbidden)

        namespace = {}
        exec(source, namespace)
        self.assertIn("product:WHEAT:increase", namespace["MODELS"])
        got = namespace["score"]("product:WHEAT:increase", rows[0]["features"])
        self.assertIsInstance(got, float)
        self.assertIsNone(namespace["score"]("no_such_output_id", rows[0]["features"]))


if __name__ == "__main__":
    unittest.main()
