"""CPU correctness checks for free-response conversion, parsing, and scoring."""

import copy
import unittest

from answer_protocol import (AnswerFormatError, DOMAIN_ORDER, format_answer,
                             oracle_answer, parse_response, render_ascii_prompt,
                             response_correct, score_completed_responses, typed_equal)
from materialize_data import canonical_key, load_upstream, normalize_row


class AnswerParserTests(unittest.TestCase):
    def test_permitted_scalars_and_reasoning(self):
        for value in [True, False, 0, -47, 100000000, "not_present", "event_SCENE_2", ""]:
            with self.subTest(value=value):
                response = "First apply the given rules.\n\n" + format_answer(value) + "\n\n"
                self.assertTrue(typed_equal(parse_response(response), value))

    def test_rejects_ambiguous_or_incomplete_answers(self):
        invalid = [
            "14", "Final answer: ", "Final answer: 1.0", "Final answer: 1e0",
            "Final answer: null", "Final answer: []", 'Final answer: {"answer": 1}',
            "Final answer: NaN", "Final answer: Infinity", "Final answer: -Infinity",
            "Final answer: 12 extra", "Final answer: 1 2", "Final answer: true\nDone.",
            "Final answer: 1\nFinal answer: 1", "I mention Final answer: here.\nFinal answer: 1",
            "  Final answer: 1", "Final answer:1", "Final answer: 01", 'Final answer: "unterminated',
        ]
        for response in invalid:
            with self.subTest(response=response):
                with self.assertRaises(AnswerFormatError):
                    parse_response(response)
                self.assertFalse(response_correct(response, 1))

    def test_type_sensitive_comparison(self):
        self.assertFalse(response_correct("Final answer: true", 1))
        self.assertFalse(response_correct("Final answer: 1", True))
        self.assertFalse(response_correct('Final answer: "1"', 1))
        self.assertTrue(response_correct("Final answer: -0", 0))
        self.assertFalse(response_correct('Final answer: "Direct"', "direct"))


class ConversionAndOracleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.domains, cls.generate_cases, cls.validate_records = load_upstream()
        cls.rows = [normalize_row(case[0]) for case in cls.generate_cases(700, 76109)]

    def test_all_domains_and_both_regimes_match_independent_oracles(self):
        self.assertEqual({(r["domain"], r["regime"]) for r in self.rows},
                         {(d, s) for d in DOMAIN_ORDER for s in ("id", "ood")})
        for row in self.rows:
            self.assertTrue(typed_equal(row["answer"], oracle_answer(row)))
            self.assertNotIn("options", row)
            self.assertNotIn("target", row)
            self.assertNotIn("record_id", row["state"])
            expected_type = bool if row["domain"] == "formal_logic" else int if row["domain"] in ("arithmetic", "code_semantics") else None
            if expected_type:
                self.assertIs(type(row["answer"]), expected_type)

    def test_conversion_does_not_read_option_descriptions_or_source_target(self):
        source = next(type(self).generate_cases(1, 76109))[0]
        expected = normalize_row(source)
        source["options"] = ["wrong descriptions"]
        source["target"] = [0]
        self.assertEqual(normalize_row(source), expected)

    def test_renderer_and_dedup_exclude_supervision_and_audit_fields(self):
        row = copy.deepcopy(self.rows[0])
        original_prompt, original_key = render_ascii_prompt(row), canonical_key(row)
        row.update(answer="SENSITIVE ANSWER", domain="SENSITIVE DOMAIN", id="SECRET ID", source_split="SECRET SOURCE")
        self.assertEqual(render_ascii_prompt(row), original_prompt)
        self.assertEqual(canonical_key(row), original_key)
        self.assertTrue(original_prompt.endswith("[response]"))
        self.assertNotIn("[options]", original_prompt)
        self.assertNotIn("[kind]", original_prompt)
        row["question"] += " A changed question."
        self.assertNotEqual(canonical_key(row), original_key)

    def test_temporal_names_are_normalized_together(self):
        for row in self.rows:
            if row["domain"] == "temporal":
                self.assertIn(row["answer"], {event["id"] for event in row["state"]["events"]})
                self.assertRegex(row["answer"], r"^event_SCENE_[0-4]$")

    def test_independent_oracles_known_edge_cases(self):
        arithmetic = {"domain": "arithmetic", "state": {"expression": "(a // b) - abs(c)", "values": {"a": -5, "b": 2, "c": -3}}}
        self.assertEqual(oracle_answer(arithmetic), -6)
        algorithm = {"domain": "algorithms", "state": {"values": [1, 3, 5], "divisor": 2, "order": "ascending", "zero_based_index": 0}}
        self.assertEqual(oracle_answer(algorithm), "not_present")
        graph = {"domain": "relations", "state": {"start": "a", "goal": "c", "directed_edges": [["a", "b"], ["b", "a"], ["b", "c"]]}}
        self.assertEqual(oracle_answer(graph), "indirect")
        graph["state"]["directed_edges"].append(["a", "c"])
        self.assertEqual(oracle_answer(graph), "direct")

    def test_diagnostic_helper_can_score_small_complete_fixtures(self):
        selected = {(row["domain"], row["regime"]): row for row in self.rows}
        rows = list(selected.values())
        responses = [format_answer(row["answer"]) for row in rows]
        score = score_completed_responses(rows, responses)
        self.assertEqual(score["score"], 100)
        self.assertTrue(score["all_answers_correct"])
        responses[0] = "Malformed completed response"
        score = score_completed_responses(rows, responses)
        self.assertLess(score["score"], 100)
        self.assertEqual(score["correct"], 13)
        with self.assertRaises(ValueError):
            score_completed_responses(rows, responses[:-1])


if __name__ == "__main__":
    unittest.main()
