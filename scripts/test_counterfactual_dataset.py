import unittest

import counterfactual_dataset as cd


class CounterfactualDatasetTests(unittest.TestCase):
    def test_checkpoints_are_deduplicated_with_both_reasons(self):
        rows = cd.checkpoint_specs(100)
        self.assertEqual(len({x["step"] for x in rows}), len(rows))
        self.assertEqual(rows[3]["reasons"], ["day_start", "shop_unlock"])

    def test_label_boundaries_are_neutral(self):
        self.assertEqual(cd.label_delta(250, False), 0)
        self.assertEqual(cd.label_delta(-250, False), 0)
        self.assertEqual(cd.label_delta(251, False), 1)
        self.assertEqual(cd.label_delta(-251, False), -1)
        self.assertEqual(cd.label_delta(999, True), -1)

    def test_schema_is_stable_and_unique(self):
        self.assertEqual(len(cd.FEATURE_ORDER), len(set(cd.FEATURE_ORDER)))
        self.assertEqual(len(cd.SCHEMA_HASH), 64)

    def test_remove_hire_is_bounded_and_audited(self):
        base = lambda obs: {"farmer": ["PASS"], "hands": [], "market": [["HIRE"], ["HIRE"]]}
        wrapper = cd.RecordingAgent(base, 0, {"kind": "hand_remove_one", "item": None, "target": None, "remaining": 1})
        action = wrapper({"step": 0, "day": 0, "hour": 0})
        self.assertEqual(action["market"], [["HIRE"]])
        self.assertEqual(wrapper.audit["applied"], 1)
        action = wrapper({"step": 1, "day": 0, "hour": 1})
        self.assertEqual(action["market"], [["HIRE"], ["HIRE"]])

    def test_modeled_output_mapping(self):
        self.assertEqual(cd.modeled_output_id({"kind": "crop_add_two", "item": "MELON"}),
                         "product:MELON:increase")
        self.assertEqual(cd.modeled_output_id({"kind": "crop_redirect_two", "item": "MELON", "target": "WHEAT"}),
                         "product:WHEAT:increase")
        self.assertEqual(cd.modeled_output_id({"kind": "animal_defer_one", "item": "COW"}),
                         "product:MILK:avoid")
        self.assertEqual(cd.modeled_output_id({"kind": "land_advance", "item": None}),
                         "competitive_expansion")

    def test_task_construction_is_deterministic_and_alternating(self):
        opponents = ["starter", "strategies_v2.ring.agent"]
        first = cd.build_tasks(5, 20, opponents, 100)
        self.assertEqual(first, cd.build_tasks(5, 20, opponents, 100))
        self.assertEqual([x["seed"] for x in first], [20, 21, 22, 23, 24])
        self.assertEqual([x["pair_index"] % 2 for x in first], [0, 1, 0, 1, 0])
        self.assertEqual([x["opponent_name"] for x in first],
                         ["starter", "strategies_v2.ring.agent", "starter", "strategies_v2.ring.agent", "starter"])


if __name__ == "__main__":
    unittest.main()
