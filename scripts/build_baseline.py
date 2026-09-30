#!/usr/bin/env python3
"""Rebuild the exact 20,000-row procedural B1 reference corpus using CPU only.

python3 scripts/build_baseline.py
python3 scripts/build_baseline.py --check

Reads only public source data. Does not load models, read Judge data, train B1,
or provide a production-cost meter. A real Work run must meter or inherit the
reference corpus's generation cost under configs/baseline.json.
"""

from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import random

from answer_protocol import format_answer, oracle_answer, typed_equal
from materialize_data import (ROOT, SOURCE_COMMIT, SOURCE_HASHES, canonical_key,
                              digest, emit, jsonl_bytes, load_upstream, packed,
                              summarize, synthesis_partition, validate_free_response)


CONFIG_PATH = "configs/baseline.json"
PUBLIC_PATHS = ("data/public/train.jsonl", "data/public/development.jsonl",
                "data/public/reference.jsonl")


def read_jsonl(path):
    return [json.loads(line) for line in path.read_text().splitlines() if line]


def build_candidate(builder, domain, rng):
    """Run the untouched ID builder, retaining native semantics and answer type."""
    state, question, _options, answer, _auxiliary = builder(rng, "SCENE", False)
    if domain == "formal_logic":
        if answer not in ("true", "false"):
            raise ValueError("Unexpected native Boolean answer")
        answer = answer == "true"
    elif domain in ("arithmetic", "code_semantics") or (domain == "algorithms" and answer != "not_present"):
        answer = int(answer)
    row = json.loads(packed({"kind": "free_response", "state": state,
                            "question": question, "answer": answer,
                            "domain": domain, "regime": "id",
                            "source_split": "baseline_procedural"}))
    validate_free_response(row)
    return row


def build_corpus(config, seed_rows, heldout_rows, builders):
    generation = config["generation"]
    domains = tuple(generation["domains"])
    quotas = generation["quota_by_domain"]
    if set(quotas) != set(domains) or set(domains) != set(builders):
        raise ValueError("Domain/builder/quota mismatch")
    if len(seed_rows) != generation["fixed_seed_rows"]:
        raise ValueError("Unexpected seed count")
    if sum(quotas.values()) != generation["total_unique_rows"]:
        raise ValueError("Quotas do not sum to the corpus size")
    heldout = {canonical_key(row) for row in heldout_rows}
    seen = set()
    rows, provenance = [], []
    counts = Counter()
    for original in seed_rows:
        validate_free_response(original)
        key = canonical_key(original)
        if original["regime"] != "id" or key in seen or key in heldout:
            raise ValueError("Seed data contains OOD, duplicate or held-out overlap")
        seen.add(key)
        rows.append(dict(original))
        counts[original["domain"]] += 1
        provenance.append({"origin": "provided_seed", "source_row_id": original["id"],
                           "canonical_sha256": key, "generation_attempt": None})
    if any(counts[domain] > quotas[domain] for domain in domains):
        raise ValueError("Seed data already exceeds a domain quota")

    rng = random.Random(generation["seed"])
    attempts = 0
    by_domain_attempts = Counter()
    rejects = Counter()
    rejected_by_domain = Counter()
    while any(counts[d] < quotas[d] for d in domains):
        for domain in domains:
            if counts[domain] == quotas[domain]:
                continue
            if attempts >= generation["max_attempts"]:
                raise ValueError("B1 could not fill quotas inside the generation-attempt cap")
            attempts += 1
            by_domain_attempts[domain] += 1
            row = build_candidate(builders[domain], domain, rng)
            key = canonical_key(row)
            reason = ("reserved_partition" if synthesis_partition(row) != "train" else
                      "development_or_reference_duplicate" if key in heldout else
                      "existing_corpus_duplicate" if key in seen else None)
            if reason:
                rejects[reason] += 1
                rejected_by_domain[f"{domain}/{reason}"] += 1
                continue
            counts[domain] += 1
            seen.add(key)
            rows.append(row)
            provenance.append({"origin": "procedural_id", "canonical_sha256": key,
                               "generation_attempt": attempts,
                               "domain_generation_attempt": by_domain_attempts[domain]})

    for index, (row, origin) in enumerate(zip(rows, provenance)):
        row["id"] = row["group_id"] = f"baseline-{index:06d}"
        origin["id"] = row["id"]
    stats = {"seed_rows": len(seed_rows), "new_rows": len(rows) - len(seed_rows),
             "attempts": attempts, "accepted": len(rows) - len(seed_rows),
             "rejected": sum(rejects.values()),
             "attempts_by_domain": dict(sorted(by_domain_attempts.items())),
             "rejections_by_reason": dict(sorted(rejects.items())),
             "rejections_by_domain_reason": dict(sorted(rejected_by_domain.items())),
             "quota_counts": dict(sorted(counts.items()))}
    if stats["attempts"] != stats["accepted"] + stats["rejected"]:
        raise ValueError("Attempt accounting inconsistency")
    return rows, provenance, stats


def epoch_order(size, rng):
    """Frozen B1 order: use the SAME seeded RNG object across successive calls."""
    indices = list(range(size))
    rng.shuffle(indices)
    return indices


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Rebuild and byte-compare; never write")
    args = parser.parse_args()
    config_bytes = (ROOT / CONFIG_PATH).read_bytes()
    config = json.loads(config_bytes)
    domains, _, _ = load_upstream()
    from jev.case_reasoning import BUILDERS
    if tuple(config["generation"]["domains"]) != domains:
        raise ValueError("Domain order differs from the pinned source")
    public_bytes = {path: (ROOT / path).read_bytes() for path in PUBLIC_PATHS}
    datasets = {path: [json.loads(line) for line in data.splitlines()] for path, data in public_bytes.items()}
    seed_rows = datasets[PUBLIC_PATHS[0]]
    heldout_rows = datasets[PUBLIC_PATHS[1]] + datasets[PUBLIC_PATHS[2]]
    rows, provenance, generation_stats = build_corpus(config, seed_rows, heldout_rows, BUILDERS)
    corpus = jsonl_bytes(rows)
    origins = jsonl_bytes(provenance)
    order_rng = random.Random(config["training"]["dataloader_seed"])
    first_epoch = epoch_order(len(rows), order_rng)
    second_epoch = epoch_order(len(rows), order_rng)
    manifest = {
        "schema_version": 1, "baseline": "B1", "config_path": CONFIG_PATH,
        "config_sha256": digest(config_bytes), "source_commit": SOURCE_COMMIT,
        "source_files_sha256": SOURCE_HASHES,
        "public_inputs_sha256": {path: digest(data) for path, data in public_bytes.items()},
        "generation": generation_stats,
        "files": {"data/baseline/train.jsonl": {"sha256": digest(corpus), "bytes": len(corpus), **summarize(rows)},
                  "data/baseline/provenance.jsonl": {"sha256": digest(origins), "bytes": len(origins), "rows": len(provenance)}},
        "target": "format_answer(answer) plus exactly one original EOS token; no rationale for B1",
        "dataloader": {"first_epoch_indices_json_sha256": digest(packed(first_epoch).encode()),
                       "second_epoch_indices_json_sha256": digest(packed(second_epoch).encode()),
                       "hash_serialization": "Canonical JSON compact list of zero-based indices; no trailing newline"},
        "training_has_run": False,
        "production_cost": "Not measured. Rebuild in metered Work or inherit verified costs; this materialized corpus is not a free expansion of the seed pool."
    }
    keys = {canonical_key(row) for row in rows}
    heldout_keys = {canonical_key(row) for row in heldout_rows}
    seed_keys = {canonical_key(row) for row in seed_rows}
    audit = {
        "schema_version": 1, "status": "passed",
        "generation": generation_stats,
        "unique_normalized_inputs": len(keys),
        "all_fixed_seeds_included": seed_keys <= keys,
        "development_reference_overlap": len(keys & heldout_keys),
        "all_new_rows_in_training_partition": all(synthesis_partition(row) == "train" for row in rows[len(seed_rows):]),
        "all_rows_id_only": all(row["regime"] == "id" for row in rows),
        "all_answers_match_independent_oracle": all(typed_equal(row["answer"], oracle_answer(row)) for row in rows),
        "canonical_target_examples": {d: format_answer(next(r for r in rows if r["domain"] == d)["answer"]) for d in domains},
        "source_builders_used_unmodified": True,
        "private_data_read": False, "teacher_used": False, "model_loaded": False, "gpu_used": False,
        "corpus_sha256": digest(corpus), "provenance_sha256": digest(origins),
        "config_sha256": digest(config_bytes),
        "limits": ["Reference corpus generation only; no student training or B1 accuracy measured",
                   "No tokenizer-length measurement or H100 elapsed-time measurement",
                   "Semantic train recipe and reuse-cost contract require the task-owned runtime adapter and meter",
                   "Fixed seeds/order do not guarantee bitwise reproducibility across GPU software stacks"]
    }
    emit("data/baseline/train.jsonl", corpus, args.check)
    emit("data/baseline/provenance.jsonl", origins, args.check)
    emit("data/baseline/manifest.json", (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode(), args.check)
    emit("evidence/baseline_audit.json", (json.dumps(audit, indent=2, sort_keys=True) + "\n").encode(), args.check)
    print(json.dumps({"status": "verified" if args.check else "materialized",
                      "rows": len(rows), "corpus_sha256": digest(corpus),
                      **generation_stats}, indent=2))


if __name__ == "__main__":
    main()
