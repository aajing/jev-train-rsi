"""Strict Judge gate tests using synthetic fixtures, never hidden gold data."""

import contextlib
import copy
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest

from answer_protocol import DOMAIN_ORDER, format_answer
from judge_gate import (JUDGE_KEY, JudgeValidationError, load_frozen_dataset,
                        load_responses, main, score_frozen_judge)


class FrozenJudgeGateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.dataset = root / "judge.jsonl"
        self.manifest = root / "manifest.json"
        self.response_file = root / "responses.jsonl"
        self.rows = [{"id": f"synthetic-{domain}-{regime}-{index}",
                      "domain": domain, "regime": regime,
                      "state": {"synthetic_index": index},
                      "question": "Synthetic fixture only", "answer": index}
                     for domain in DOMAIN_ORDER for regime in ("id", "ood")
                     for index in range(200)]
        self.responses = [{"id": row["id"], "response": format_answer(row["answer"])}
                          for row in self.rows]
        self.write_dataset(self.rows)

    def write_dataset(self, rows, *, manifest_count=2800):
        raw = "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows).encode()
        self.dataset.write_bytes(raw)
        manifest = {"files": {JUDGE_KEY: {
            "sha256": hashlib.sha256(raw).hexdigest(), "rows": manifest_count,
            "bytes": len(raw),
            "by_domain_regime": {domain + "/" + regime: 200
                                 for domain in DOMAIN_ORDER for regime in ("id", "ood")}}}}
        self.manifest.write_text(json.dumps(manifest), encoding="utf-8")

    def score(self, responses=None, **kwargs):
        return score_frozen_judge(self.dataset, self.manifest,
                                  self.responses if responses is None else responses, **kwargs)

    def test_complete_2800_correct_is_100_pending_external_eligibility(self):
        result = self.score()
        self.assertEqual(result["score"], 100)
        self.assertEqual(result["correct"], 2800)
        self.assertEqual(result["total"], 2800)
        self.assertTrue(result["all_answers_correct"])
        self.assertTrue(result["data_integrity_verified"])
        self.assertTrue(result["responses_complete"])
        self.assertFalse(result["eligibility_checked"])

    def test_one_wrong_is_not_rounded_to_full_score(self):
        self.responses[0]["response"] = "Final answer: -1000"
        result = self.score()
        self.assertEqual(result["score"], 100 * 2799 / 2800)
        self.assertAlmostEqual(result["score"], 99.96428571428571)
        self.assertFalse(result["all_answers_correct"])

    def test_empty_completed_response_is_wrong_and_still_complete(self):
        self.responses[0]["response"] = ""
        result = self.score()
        self.assertEqual(result["correct"], 2799)
        self.assertTrue(result["responses_complete"])

    def test_boolean_is_not_an_integer_gold_answer(self):
        self.responses[0]["response"] = "Final answer: false"
        self.assertEqual(self.score()["correct"], 2799)

    def test_responses_are_aligned_by_id_not_position(self):
        self.assertEqual(self.score(list(reversed(self.responses)))["score"], 100)
        mapping = {row["id"]: row["response"] for row in reversed(self.responses)}
        self.assertEqual(self.score(mapping)["score"], 100)

    def test_missing_duplicate_extra_and_replaced_response_ids_rejected(self):
        invalid_sets = {
            "missing": self.responses[:-1],
            "duplicate": self.responses + [self.responses[0]],
            "extra": self.responses + [{"id": "unexpected", "response": "Final answer: 0"}],
            "replaced": self.responses[:-1] + [{"id": "unexpected", "response": "Final answer: 0"}],
        }
        for scenario, responses in invalid_sets.items():
            with self.subTest(scenario=scenario):
                with self.assertRaises(JudgeValidationError):
                    self.score(responses)

    def test_duplicate_response_id_with_same_total_rejected(self):
        responses = self.responses[:-1] + [self.responses[0]]
        with self.assertRaisesRegex(JudgeValidationError, "Duplicate response ID"):
            self.score(responses)

    def test_response_payload_schema_is_strict(self):
        invalid = [
            {"id": self.rows[0]["id"]},
            {"id": self.rows[0]["id"], "response": None},
            {"id": self.rows[0]["id"], "response": "x", "answer": 0},
            {"id": 0, "response": "x"},
        ]
        for row in invalid:
            with self.subTest(row=row):
                with self.assertRaises(JudgeValidationError):
                    self.score([row] + self.responses[1:])

    def test_dataset_sha_mismatch_rejected_before_scoring(self):
        self.dataset.write_bytes(self.dataset.read_bytes() + b" ")
        with self.assertRaisesRegex(JudgeValidationError, "SHA256 mismatch"):
            self.score()

    def test_manifest_pin_rejects_changed_manifest(self):
        pin = hashlib.sha256(self.manifest.read_bytes()).hexdigest()
        self.assertEqual(self.score(manifest_sha256=pin)["score"], 100)
        self.manifest.write_bytes(self.manifest.read_bytes() + b"\n")
        with self.assertRaisesRegex(JudgeValidationError, "Manifest SHA256 mismatch"):
            self.score(manifest_sha256=pin)

    def test_fourteen_correct_rows_cannot_receive_an_official_score(self):
        rows = [row for row in self.rows if row["answer"] == 0]
        self.assertEqual(len(rows), 14)
        responses = [{"id": row["id"], "response": format_answer(row["answer"])}
                     for row in rows]
        # Reject even when a matching file hash is present in the fixture manifest.
        self.write_dataset(rows)
        with self.assertRaisesRegex(JudgeValidationError, "exactly 2800 rows"):
            self.score(responses)
        self.write_dataset(rows, manifest_count=14)
        with self.assertRaisesRegex(JudgeValidationError, "exactly 2800 Judge rows"):
            self.score(responses)

    def test_duplicate_dataset_ids_rejected_even_with_matching_hash(self):
        rows = copy.deepcopy(self.rows)
        rows[-1]["id"] = rows[0]["id"]
        self.write_dataset(rows)
        with self.assertRaisesRegex(JudgeValidationError, "Duplicate Judge dataset ID"):
            self.score()

    def test_unequal_cell_sizes_rejected_even_with_matching_hash(self):
        rows = copy.deepcopy(self.rows)
        rows[0]["regime"] = "ood"
        self.write_dataset(rows)
        with self.assertRaisesRegex(JudgeValidationError, "exactly 200 rows"):
            self.score()

    def test_duplicate_json_keys_are_not_silently_overwritten(self):
        self.response_file.write_text(
            '{"id":"one","id":"two","response":"Final answer: 0"}\n', encoding="utf-8")
        with self.assertRaisesRegex(JudgeValidationError, "Duplicate JSON object key"):
            load_responses(self.response_file)

    def test_cli_returns_aggregate_results_and_rejects_incomplete_responses(self):
        args = ["--dataset", str(self.dataset), "--manifest", str(self.manifest),
                "--responses", str(self.response_file)]
        self.response_file.write_text(
            "".join(json.dumps(row) + "\n" for row in self.responses), encoding="utf-8")
        output, error = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(error):
            status = main(args)
        result = json.loads(output.getvalue())
        self.assertEqual(status, 0)
        self.assertTrue(result["scored"])
        self.assertEqual(result["score"], 100)
        self.assertNotIn("synthetic-", output.getvalue())
        self.assertEqual(error.getvalue(), "")
        self.response_file.write_text(json.dumps(self.responses[0]) + "\n", encoding="utf-8")
        output, error = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(error):
            status = main(args)
        self.assertEqual(status, 2)
        self.assertEqual(output.getvalue(), "")
        self.assertFalse(json.loads(error.getvalue())["scored"])


if __name__ == "__main__":
    unittest.main()
