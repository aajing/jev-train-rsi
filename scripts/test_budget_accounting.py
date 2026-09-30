"""Budget tests focus on reuse, rejected work and time double-counting."""

import copy
import unittest

from budget_accounting import account_candidate


def receipt(origin, seconds=20, parents=(), attempts=3, input_tokens=10, output_tokens=5):
    return {"origin_candidate_id": origin, "parent_ids": list(parents),
            "generation_seconds": seconds, "proposed_states": attempts,
            "teacher_input_tokens": input_tokens, "teacher_output_tokens": output_tokens}


class AccountingTests(unittest.TestCase):
    def test_shared_cached_ancestor_charged_once(self):
        receipts = {"root": receipt("prior", 30),
                    "left": receipt("prior", 20, ["root"]),
                    "right": receipt("prior", 10, ["root"]),
                    "new": receipt("now", 25),
                    "discarded": receipt("now", 5)}
        report = account_candidate("now", 100, 1000, 5000,
                                   ["new", "discarded"], ["left", "right", "left", "new"], receipts)
        self.assertEqual(report["counts"]["candidate_production_charged_seconds"], 160)
        self.assertEqual(report["counts"]["candidate_proposed_state_attempts"], 15)
        self.assertEqual(report["counts"]["candidate_teacher_input_output_tokens"], 75)
        self.assertEqual(report["trajectory_inherited_time_added"], 0)
        self.assertTrue(report["numeric_budget_pass"])

    def test_missing_discarded_current_work_is_rejected(self):
        with self.assertRaises(ValueError):
            account_candidate("now", 100, 1, 1, ["used"], ["used"],
                              {"used": receipt("now"), "rejected": receipt("now")})

    def test_inherited_time_can_exceed_candidate_budget(self):
        report = account_candidate("now", 7000, 1, 1, [], ["old"],
                                   {"old": receipt("prior", 201)})
        self.assertFalse(report["numeric_budget_pass"])
        self.assertIn("candidate_production_charged_seconds", report["exceeded_limits"])

    def test_current_time_not_charged_twice(self):
        report = account_candidate("now", 7200, 20000, 20000000, ["new"], ["new"],
                                   {"new": receipt("now", 120, attempts=100000,
                                                   input_tokens=1000000, output_tokens=1000000)})
        self.assertTrue(report["numeric_budget_pass"])
        self.assertEqual(report["counts"]["candidate_production_charged_seconds"], 7200)

    def test_bad_ancestry_and_values_are_rejected(self):
        bad = [
            {"r": receipt("prior", parents=["missing"])},
            {"r": receipt("prior", parents=["r"])},
            {"r": receipt("prior", seconds=float("nan"))},
            {"r": receipt("prior", attempts=-1)},
        ]
        for receipts in bad:
            with self.subTest(receipts=receipts), self.assertRaises(ValueError):
                account_candidate("now", 100, 1, 1, [], ["r"], receipts)

    def test_each_cap_is_enforced(self):
        from budget_accounting import DEFAULT_LIMITS
        import json
        limits = json.loads(DEFAULT_LIMITS.read_text())
        for key in ("candidate_proposed_state_attempts", "candidate_teacher_input_output_tokens",
                    "candidate_distinct_training_states", "candidate_student_nonpadding_token_exposures"):
            reduced = copy.deepcopy(limits)
            reduced[key] = 0
            report = account_candidate("now", 100, 1, 1, ["r"], ["r"],
                                       {"r": receipt("now")}, reduced)
            self.assertIn(key, report["exceeded_limits"])


if __name__ == "__main__":
    unittest.main()
