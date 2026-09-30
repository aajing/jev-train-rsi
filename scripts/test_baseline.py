"""CPU checks of B1 rejection accounting, fixed ordering and corpus integrity."""

import copy
import json
import random
import unittest
from unittest.mock import patch

from build_baseline import build_candidate, build_corpus, epoch_order, read_jsonl
from materialize_data import ROOT, canonical_key, load_upstream, synthesis_partition


class BaselineGenerationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        load_upstream()
        from jev.case_reasoning import BUILDERS
        cls.builders = BUILDERS
        cls.config = json.loads((ROOT / "configs/baseline.json").read_text())

    def small_config(self, total=2, cap=100):
        config = copy.deepcopy(self.config)
        config["generation"].update(domains=["formal_logic"],
                                    quota_by_domain={"formal_logic": total},
                                    fixed_seed_rows=0, total_unique_rows=total,
                                    max_attempts=cap)
        return config

    def two_rows(self):
        rng = random.Random(1234)
        rows = {}
        while len(rows) < 2:
            row = build_candidate(self.builders["formal_logic"], "formal_logic", rng)
            rows[canonical_key(row)] = row
        return list(rows.values())

    def test_rejected_partition_and_duplicates_spend_attempts_and_advance_rng(self):
        first, second = self.two_rows()
        proposals = [first, first, first, second]
        draws = []

        def candidate(_builder, _domain, rng):
            draws.append(rng.random())
            return copy.deepcopy(proposals[len(draws) - 1])

        with patch("build_baseline.build_candidate", side_effect=candidate), \
             patch("build_baseline.synthesis_partition", side_effect=["judge", "train", "train", "train"]):
            rows, origins, stats = build_corpus(self.small_config(cap=4), [], [],
                                               {"formal_logic": self.builders["formal_logic"]})
        expected_rng = random.Random(20260930)
        self.assertEqual(draws, [expected_rng.random() for _ in range(4)])
        self.assertEqual(stats["attempts"], 4)
        self.assertEqual(stats["accepted"], 2)
        self.assertEqual(stats["rejections_by_reason"], {"reserved_partition": 1, "existing_corpus_duplicate": 1})
        self.assertEqual([p["generation_attempt"] for p in origins], [2, 4])
        self.assertEqual([r["id"] for r in rows], ["baseline-000000", "baseline-000001"])

    def test_attempt_ceiling_fails_without_returning_partial_corpus(self):
        first, _ = self.two_rows()
        with patch("build_baseline.build_candidate", return_value=first), \
             patch("build_baseline.synthesis_partition", return_value="judge"):
            with self.assertRaisesRegex(ValueError, "generation-attempt cap"):
                build_corpus(self.small_config(cap=3), [], [],
                             {"formal_logic": self.builders["formal_logic"]})

    def test_heldout_row_is_rejected_even_inside_training_partition(self):
        first, second = self.two_rows()
        with patch("build_baseline.build_candidate", side_effect=[first, second]), \
             patch("build_baseline.synthesis_partition", return_value="train"):
            rows, _, stats = build_corpus(self.small_config(total=1, cap=2), [], [first],
                                          {"formal_logic": self.builders["formal_logic"]})
        self.assertEqual(canonical_key(rows[0]), canonical_key(second))
        self.assertEqual(stats["rejections_by_reason"], {"development_or_reference_duplicate": 1})

    def test_epoch_rng_continues_across_epochs(self):
        a, b = random.Random(42), random.Random(42)
        epochs_a = [epoch_order(100, a) for _ in range(2)]
        epochs_b = [epoch_order(100, b) for _ in range(2)]
        self.assertEqual(epochs_a, epochs_b)
        self.assertNotEqual(epochs_a[0], epochs_a[1])
        self.assertEqual(sorted(epochs_a[0]), list(range(100)))

    def test_materialized_corpus_keeps_all_seeds_and_excludes_heldout(self):
        rows = read_jsonl(ROOT / "data/baseline/train.jsonl")
        seeds = read_jsonl(ROOT / "data/public/train.jsonl")
        heldout = (read_jsonl(ROOT / "data/public/development.jsonl") +
                   read_jsonl(ROOT / "data/public/reference.jsonl"))
        keys = [canonical_key(row) for row in rows]
        self.assertEqual(len(keys), 20000)
        self.assertEqual(len(set(keys)), 20000)
        self.assertEqual(keys[:1800], [canonical_key(row) for row in seeds])
        self.assertFalse(set(keys) & {canonical_key(row) for row in heldout})
        self.assertTrue(all(synthesis_partition(row) == "train" for row in rows[1800:]))
        for domain, count in self.config["generation"]["quota_by_domain"].items():
            self.assertEqual(sum(row["domain"] == domain for row in rows), count)


if __name__ == "__main__":
    unittest.main()
