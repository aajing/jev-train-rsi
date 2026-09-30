#!/usr/bin/env python3
"""Materialize and audit free-response data from pinned Open-Jev scenes.

No model, GPU, network, or third-party Python package is used.  The private
generator seed and all Judge examples belong to Judge only, never Work.

Run once: python3 scripts/materialize_data.py
Verify a deterministic rebuild: python3 scripts/materialize_data.py --check
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import json
import os
from pathlib import Path
import random
import re
import secrets
import sys

from answer_protocol import (is_scalar, oracle_answer, render_ascii_prompt,
                             typed_equal, PROMPT_INSTRUCTION)


ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = ROOT / "sources" / "open-jev"
SOURCE_COMMIT = "3308a15ccd7eea1df7a37d6ddc39b023b801ba16"
SOURCE_HASHES = {
    "jev/__init__.py": "039d6c25d5ebea9724711756aff885f44d2226abbeea4abb99dfbc7b0b35ce7e",
    "jev/api.py": "493f1fb9c3ffccbdc5f07d555791f9d86b3db7e1a53eef278230211cb6883254",
    "jev/data.py": "97c1764a5090f60476397baf889a864359e0d59b48d99ddf3b34335d3e1b138e",
    "jev/metrics.py": "cb460c78b877a24708a0a8f8ca6b51f9602491f6ea24cd14e9a828c03d92f78b",
    "jev/case_reasoning.py": "4aa15762bcdbad3c355c13e1ed9a1d512cefecfdf856238d1d33f44d6fa3761a",
    "LICENSE": "ef2f6f6db605a2f611bc2d037c59276f615cdea76ac6e7551a28f71db890c9d2",
}
UPSTREAM_HASHES = {
    "train": "147f38dbfd622e58d7669bf4e956ba15c0377fd4c80a6a4e45a40723698e258b",
    "calibration": "a0d3cddf132630d6b74601673db7bf9f778fcc04d722cfffd5f44cea296b59be",
    "validation": "146aa3be0e7a0d59693adb248ab4687cc0e4b21e5bc07805fbfcdedb5258ceeb",
    "test": "bc36ff12ff82d14e0d99ce98db2494a4559abcf118e5fa0b09e67dcf8b90dd61",
    "ood": "a23835a8569c2c7011cbd5855393c54f00c8e054c597399f3f036d1ef4d1e399",
}
PUBLIC_SEED = 76109
PUBLIC_GROUPS = 2500
PRIVATE_PER_CELL = 200
PRIVATE_MAX_GROUPS = 5000000
SPLIT_PRIORITY = ("test", "ood", "validation", "calibration", "train")
REGIMES = ("id", "ood")
JUDGE_STRATA = {
    "formal_logic": {"false": 100, "true": 100},
    "relations": {"direct": 67, "indirect": 67, "unreachable": 66},
    "arithmetic": {"negative": 80, "zero": 40, "positive": 80},
    "temporal": {"earliest": 100, "latest": 100},
    "code_semantics": {"negative": 80, "zero": 40, "positive": 80},
    "algorithms": {"present": 100, "not_present": 100},
    "evidence_integration": {"conflict": 40, "not_stated": 40,
                             "queued": 30, "active": 30, "paused": 30, "closed": 30},
}


def packed(value, *, ascii_only=False):
    return json.dumps(value, ensure_ascii=ascii_only, sort_keys=True,
                      separators=(",", ":"), allow_nan=False)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def load_upstream():
    for rel, expected in SOURCE_HASHES.items():
        if digest((SOURCE_ROOT / rel).read_bytes()) != expected:
            raise ValueError(f"Pinned source hash mismatch: {rel}")
    sys.path.insert(0, str(SOURCE_ROOT))
    from jev.case_reasoning import DOMAINS, generate_cases
    from jev.data import validate_records
    return tuple(DOMAINS), generate_cases, validate_records


def normalize_row(row):
    """Remove irrelevant record IDs and rename only generated scene entities.

    Reconstruct the source builder's native answer; never parse option text.
    This is exact normalization, not semantic or template deduplication.
    """
    from jev.case_reasoning import BUILDERS

    domain = row["metadata"]["domain"]
    source_digest = digest(row["group_id"].encode())
    raw_state, raw_question, _unused_options, native_answer, _unused_auxiliary = BUILDERS[domain](
        random.Random(int(source_digest, 16)), source_digest[:6], row["split"] == "ood")
    if packed(raw_state) != packed({k: v for k, v in row["state"].items() if k != "record_id"}) or raw_question != row["question"]:
        raise ValueError("Source builder replay does not match the original state/question")
    if domain == "formal_logic":
        if native_answer not in ("true", "false"):
            raise ValueError("Invalid source Boolean answer")
        native_answer = native_answer == "true"
    elif domain in ("arithmetic", "code_semantics") or (domain == "algorithms" and native_answer != "not_present"):
        native_answer = int(native_answer)
    tag = row["state"]["record_id"][:6]
    entity = re.compile(r"(?P<prefix>p_|N|event_|device_|other_|legacy_|alias_)"
                        + re.escape(tag) + r"(?=_|\b)")

    def clean(value):
        if isinstance(value, dict):
            return {entity.sub(r"\g<prefix>SCENE", key): clean(item)
                    for key, item in value.items() if key != "record_id"}
        if isinstance(value, list):
            return [clean(item) for item in value]
        if isinstance(value, tuple):
            return [clean(item) for item in value]
        if isinstance(value, str):
            return entity.sub(r"\g<prefix>SCENE", value)
        return value

    result = {
        "kind": "free_response",
        "state": clean(row["state"]),
        "question": clean(row["question"]),
        "answer": clean(native_answer),
        "domain": domain,
        "regime": "ood" if row["split"] == "ood" else "id",
        "source_split": row["split"],
    }
    validate_free_response(result)
    return result


def validate_free_response(row):
    if row["kind"] != "free_response" or not is_scalar(row["answer"]):
        raise ValueError("Invalid free-response record")
    if "record_id" in row["state"] or any(key in row for key in ("metadata", "options", "target", "seed")):
        raise ValueError("Unexpected source-only field")
    if not typed_equal(row["answer"], oracle_answer(row)):
        raise ValueError("Independent state oracle disagrees with source native answer")


def model_input(row):
    """Only state/question render; constant kind also forms the canonical key."""
    return {key: row[key] for key in ("state", "question", "kind")}


def canonical_key(row):
    return digest(packed(model_input(row)).encode())


def synthesis_partition(row):
    """Public, deterministic partition for an already normalized candidate row.

    New synthesis may train only on buckets 0..7; Judge uses buckets 8..9.
    Existing fixed seed rows are the declared exception.  Development/reference
    duplicates remain forbidden independently of this partition.
    """
    bucket = int(canonical_key(row)[:8], 16) % 10
    return "train" if bucket < 8 else "judge"


def judge_stratum(row):
    """Frozen boundary/answer stratum; never a field in the model prompt."""
    domain, answer = row["domain"], row["answer"]
    if domain == "formal_logic":
        result = str(answer).lower()
    elif domain in ("arithmetic", "code_semantics"):
        result = "negative" if answer < 0 else "positive" if answer > 0 else "zero"
    elif domain == "temporal":
        result = "latest" if "latest" in row["question"] else "earliest"
    elif domain == "algorithms":
        result = "not_present" if answer == "not_present" else "present"
    else:
        result = answer
    if result not in JUDGE_STRATA[domain]:
        raise ValueError("Unexpected Judge stratum")
    return result


def source_choice_at(index, seed, domains):
    """Replay only source fields needed by normalization, at an original index.

    This is the unchanged generator's seed/index/builders path, with its unused
    option shuffling and two auxiliary primitives omitted. Public dry-checks
    below compare the replay fields against the actual pinned generator.
    """
    from jev.case_reasoning import BUILDERS, VERSION
    from jev.data import split_group

    group = f"{VERSION}:{seed}:{index}"
    source_digest = digest(group.encode())
    domain = domains[index % len(domains)]
    ood = index % 10 == 0
    state, question, _options, _answer, _auxiliary = BUILDERS[domain](
        random.Random(int(source_digest, 16)), source_digest[:6], ood)
    return {"group_id": group, "state": {"record_id": source_digest[:16], **state},
            "question": question, "metadata": {"domain": domain},
            "split": "ood" if ood else split_group(group, seed)}


def verify_indexed_replay(domains, generate_cases):
    """Check two complete domain/regime scheduling cycles without private data."""
    for index, case in enumerate(generate_cases(140, PUBLIC_SEED)):
        source = next(row for row in case if row["kind"] == "choice")
        indexed = source_choice_at(index, PUBLIC_SEED, domains)
        for key in ("group_id", "state", "question", "split"):
            if packed(indexed[key]) != packed(source[key]):
                raise ValueError("Indexed source replay disagrees with pinned generator")
        if indexed["metadata"]["domain"] != source["metadata"]["domain"]:
            raise ValueError("Indexed source domain replay mismatch")


def jsonl_bytes(rows):
    return b"".join((packed(row) + "\n").encode() for row in rows)


def summarize(rows):
    cells = Counter(f"{row['domain']}/{row['regime']}" for row in rows)
    return {
        "rows": len(rows),
        "by_domain_regime": dict(sorted(cells.items())),
        "by_source_split": dict(sorted(Counter(r["source_split"] for r in rows).items())),
        "answer_type_counts": dict(sorted(Counter(type(r["answer"]).__name__ for r in rows).items())),
        "synthesis_partition_counts": dict(sorted(Counter(synthesis_partition(r) for r in rows).items())),
        "max_ascii_prompt_chars": max(map(lambda r: len(render_ascii_prompt(r)), rows), default=0),
        "max_ascii_prompt_utf8_bytes": max(map(lambda r: len(render_ascii_prompt(r).encode()), rows), default=0),
        "all_answers_match_independent_oracle": all(typed_equal(r["answer"], oracle_answer(r)) for r in rows),
    }


def assign_ids(rows, prefix):
    return [dict(row, id=f"{prefix}-{i:06d}", group_id=f"{prefix}-{i:06d}")
            for i, row in enumerate(rows)]


def public_data(generate_cases, validate_records):
    official = [row for case in generate_cases(PUBLIC_GROUPS, PUBLIC_SEED) for row in case]
    summary = validate_records(official)
    hashes = {split: digest(jsonl_bytes([row for row in official if row["split"] == split]))
              for split in UPSTREAM_HASHES}
    assert hashes == UPSTREAM_HASHES, "Official three-primitive split hashes did not reproduce"
    choices = defaultdict(list)
    by_group = defaultdict(list)
    for row in official:
        by_group[row["group_id"]].append(row)
        if row["kind"] == "choice":
            choices[row["split"]].append(normalize_row(row))
    assert len(by_group) == PUBLIC_GROUPS
    assert all(len(group) == 3 and len({r["split"] for r in group}) == 1
               and sum(r["kind"] == "choice" for r in group) == 1
               for group in by_group.values())
    seen, kept, drops = {}, defaultdict(list), Counter()
    for split in SPLIT_PRIORITY:
        for row in choices[split]:
            key = canonical_key(row)
            if key in seen:
                previous_split, previous_answer = seen[key]
                if not typed_equal(previous_answer, row["answer"]):
                    raise ValueError("Conflicting labels for the same normalized input")
                drops[f"{split}_duplicate_of_{previous_split}"] += 1
                continue
            seen[key] = (split, row["answer"])
            kept[split].append(row)
    products = {
        "data/public/train.jsonl": assign_ids(kept["train"], "train"),
        "data/public/development.jsonl": assign_ids(kept["validation"] + kept["calibration"], "development"),
        "data/public/reference.jsonl": assign_ids(kept["test"] + kept["ood"], "reference"),
    }
    report = {
        "upstream_all_primitives_summary": summary,
        "upstream_all_primitives_split_sha256": hashes,
        "original_choice_counts": {split: len(choices[split]) for split in sorted(choices)},
        "normalized_retained_free_response_counts": {split: len(kept[split]) for split in sorted(choices)},
        "exact_normalized_duplicates_removed": dict(sorted(drops.items())),
        "deduplication_priority": list(SPLIT_PRIORITY),
        "original_groups_are_split_disjoint": True,
    }
    return products, set(seen), report


def private_seed(check):
    path = ROOT / "data/private/generator_seed.json"
    if path.exists():
        value = json.loads(path.read_text())
        seed = value["seed"]
        if type(seed) is not int or seed < 0 or seed == PUBLIC_SEED:
            raise ValueError("Private seed file is invalid")
        return seed
    if check:
        raise ValueError("Private seed is absent; run materialization before --check")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.parent.chmod(0o700)
    seed = secrets.randbits(128)
    value = {"access": "JUDGE_ONLY_NEVER_INCLUDE_IN_WORK_OR_PUBLIC_PROPOSAL", "seed": seed}
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w") as handle:
        handle.write(packed(value) + "\n")
    return seed


def judge_data(domains, generate_cases, public_seen, seed):
    buckets = {(domain, regime): [] for domain in domains for regime in REGIMES}
    strata = {cell: Counter() for cell in buckets}
    if set(domains) != set(JUDGE_STRATA) or any(sum(quotas.values()) != PRIVATE_PER_CELL
                                             for quotas in JUDGE_STRATA.values()):
        raise ValueError("Invalid frozen Judge stratification quotas")
    seen = set(public_seen)
    excluded = Counter()
    partition_counts = Counter()
    scans, built = 0, 0
    verify_indexed_replay(domains, generate_cases)
    for index in range(PRIVATE_MAX_GROUPS):
        scans = index + 1
        cell = (domains[index % len(domains)], "ood" if index % 10 == 0 else "id")
        if len(buckets[cell]) == PRIVATE_PER_CELL:
            continue
        source = source_choice_at(index, seed, domains)
        built += 1
        row = normalize_row(source)
        if cell != (row["domain"], row["regime"]):
            raise ValueError("Indexed replay changed domain/regime")
        key = canonical_key(row)
        partition = synthesis_partition(row)
        partition_counts[partition] += 1
        if partition != "judge":
            continue
        stratum = judge_stratum(row)
        if strata[cell][stratum] == JUDGE_STRATA[row["domain"]][stratum]:
            continue
        if key in seen:
            excluded["overlap_with_public" if key in public_seen else "within_judge"] += 1
            continue
        seen.add(key)
        # Original group IDs and the private generation seed never enter products.
        row["source_split"] = "derived_judge"
        buckets[cell].append(row)
        strata[cell][stratum] += 1
        if all(len(rows) == PRIVATE_PER_CELL for rows in buckets.values()):
            break
    if not all(len(rows) == PRIVATE_PER_CELL for rows in buckets.values()):
        deficits = {f"{domain}/{regime}": {
            stratum: quota - strata[(domain, regime)][stratum]
            for stratum, quota in JUDGE_STRATA[domain].items()
            if quota != strata[(domain, regime)][stratum]}
            for domain, regime in buckets if len(buckets[(domain, regime)]) != PRIVATE_PER_CELL}
        raise ValueError("Insufficient distinct cases under the fixed generation cap: " + packed(deficits))
    rows = [row for domain in domains for regime in REGIMES
            for row in buckets[(domain, regime)]]
    rows = assign_ids(rows, "judge")
    keys = [canonical_key(row) for row in rows]
    assert len(keys) == len(set(keys)) == len(domains) * 2 * PRIVATE_PER_CELL
    assert not (set(keys) & public_seen)
    assert all(synthesis_partition(row) == "judge" for row in rows)
    assert all(dict(strata[cell]) == JUDGE_STRATA[cell[0]] for cell in buckets)
    return rows, {
        "generated_scene_count_scanned": scans,
        "active_cell_scenes_built": built,
        "generation_scene_cap": PRIVATE_MAX_GROUPS,
        "selection": "First eligible unique scenes in original generator index order for each frozen domain/regime/stratum quota; require buckets 8..9 and exclude every public split. Skip source generation for completed domain/regime cells",
        "indexed_replay_checked_against_pinned_generator": True,
        "stratification_quotas_per_regime": JUDGE_STRATA,
        "stratification_counts": {f"{domain}/{regime}": dict(sorted(strata[(domain, regime)].items()))
                                  for domain in domains for regime in REGIMES},
        "all_stratification_quotas_satisfied": True,
        "built_scene_partition_counts": dict(sorted(partition_counts.items())),
        "all_judge_rows_in_reserved_partition": True,
        "exact_normalized_duplicates_excluded": dict(sorted(excluded.items())),
        "unique_normalized_judge_inputs": len(set(keys)),
        "normalized_cross_overlap_with_all_public_splits": 0,
        "private_seed_published": False,
    }


def emit(path, data, check, *, private=False):
    destination = ROOT / path
    if check:
        if not destination.exists() or destination.read_bytes() != data:
            raise ValueError(f"Deterministic rebuild mismatch: {path}")
    else:
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(data)
        if private:
            destination.chmod(0o600)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Rebuild in memory and compare every output without writing")
    parser.add_argument("--dry-check", action="store_true", help="Validate source, public data, and Judge quota feasibility in memory; do not write outputs")
    args = parser.parse_args()
    if args.check and args.dry_check:
        parser.error("--check and --dry-check are mutually exclusive")
    domains, generate_cases, validate_records = load_upstream()
    products, public_seen, public_report = public_data(generate_cases, validate_records)
    judge_rows, private_report = judge_data(domains, generate_cases, public_seen, private_seed(args.check or args.dry_check))
    if args.dry_check:
        print(json.dumps({"status": "quota_feasibility_verified", "public_rows": {
            path: len(rows) for path, rows in products.items()}, "judge_rows": len(judge_rows),
            "generated_scene_count_scanned": private_report["generated_scene_count_scanned"],
            "active_cell_scenes_built": private_report["active_cell_scenes_built"],
            "stratification_counts": private_report["stratification_counts"]}, indent=2))
        return
    products["data/private/judge.jsonl"] = judge_rows
    files = {}
    for path, rows in products.items():
        data = jsonl_bytes(rows)
        files[path] = {"sha256": digest(data), "bytes": len(data), **summarize(rows)}
        emit(path, data, args.check, private=path.startswith("data/private/"))
    manifest = {
        "schema_version": 3,
        "source_repository": "https://github.com/Zefan-Cai/Open-Jev",
        "source_commit": SOURCE_COMMIT,
        "source_files_sha256": SOURCE_HASHES,
        "task_files_sha256": {path: digest((ROOT / path).read_bytes()) for path in
                              ("scripts/materialize_data.py", "scripts/answer_protocol.py")},
        "dataset": "reasoning-control-v1-free-response-derived",
        "public_source_generator": {"seed": PUBLIC_SEED, "groups": PUBLIC_GROUPS},
        "model_input_fields": ["state", "question"],
        "canonical_key_fields": ["kind", "state", "question"],
        "supervision_field": "answer",
        "non_input_fields": ["kind", "id", "group_id", "answer", "domain", "regime", "source_split"],
        "development_policy": "Original validation and calibration decision scenes pooled and converted to free response; no separate temperature fitting",
        "private_policy": "data/private/ is Judge only. Never mount, package, publish or copy it into Work or a public proposal.",
        "private_seed_delivery": "Local saved file data/private/generator_seed.json; contents intentionally omitted",
        "normalization": ["Remove state.record_id", "Rename generated scene entity tags to SCENE without changing their indexed roles"],
        "duplicate_key": "SHA256 of canonical JSON of normalized state, question and constant free_response kind; no answer, options, labels or record IDs",
        "synthesis_partition": {
            "helper": "scripts/materialize_data.py:synthesis_partition",
            "rule": "bucket = int(canonical_key(normalized_row)[:8], 16) % 10",
            "new_training_buckets": list(range(8)),
            "judge_buckets": [8, 9],
            "fixed_seed_exception": "All 1800 already materialized fixed training rows remain eligible regardless of bucket; Judge excludes every public row",
            "additional_training_exclusions": "Exact normalized matches to development or public reference rows are forbidden even in buckets 0..7",
            "scope": "Prevents exact normalized new-synthesis/Judge collisions; does not guarantee semantic or template separation",
        },
        "dedup_scope_limit": "Exact normalized input equality only. No semantic equivalence or template-level leakage claim.",
        "prompt_renderer": "scripts/answer_protocol.py:render_ascii_prompt",
        "prompt_instruction": PROMPT_INSTRUCTION,
        "answer_protocol": {
            "parser": "scripts/answer_protocol.py:parse_response",
            "format": "Optional preceding reasoning; exactly one Final answer: prefix, on the last nonempty line, followed by one complete JSON boolean, integer, or string",
            "comparison": "Exact type and value; bool is distinct from int; malformed completed responses are incorrect",
            "full_score": "100 requires all 2800 answers correct, subject to candidate budget and modification-scope eligibility",
        },
        "prompt_metric_limit": "ASCII character count is not a measured tokenizer token count",
        "judge_design": {"domains": list(domains), "regimes": list(REGIMES), "unique_rows_per_cell": PRIVATE_PER_CELL,
                         "stratification_quotas_per_regime": JUDGE_STRATA,
                         "stratification_counts": private_report["stratification_counts"],
                         "score": "100 * (0.5 * mean(ID domain accuracies) + 0.5 * mean(OOD domain accuracies))",
                         "generations_per_case_for_future_evaluator": 1,
                         "future_decode": {"do_sample": False, "num_beams": 1, "max_new_tokens": 512},
                         "response_parser_implemented": True,
                         "completed_response_cpu_scorer_implemented": True,
                         "evaluator_implemented": False},
        "files": files,
    }
    report = {
        "status": "passed",
        "source_hashes_verified": True,
        "official_split_hashes_reproduced": True,
        "schema_version": 3,
        "task_files_sha256": manifest["task_files_sha256"],
        "native_source_answers_rebuilt_without_parsing_options": True,
        "normalized_answers_match_independent_state_oracles": True,
        "strict_json_scalar_schema_verified": True,
        "synthesis_partition_rule": "int(canonical_key(normalized_row)[:8], 16) % 10: new training 0..7; Judge 8..9",
        "all_private_judge_rows_in_reserved_partition": True,
        "new_synthesis_judge_exact_collision_prevention": "Disjoint public deterministic hash partitions; existing fixed training rows separately excluded from Judge",
        "oracle_provenance": "Labels come from deterministic replay of the unchanged pinned builders; independent CPU state evaluators recompute every normalized label without reading options or source labels. Arbitrary candidate admission validation is not implemented here",
        "public": public_report,
        "private": private_report,
        "files": files,
        "model_loaded": False,
        "gpu_used": False,
        "limitations": ["No model training, performance, tokenizer-length or runtime validation",
                        "No semantic/template duplicate claim",
                        "Public source reference data are not hidden",
                        "Private seed security depends on preserving the declared filesystem and task access boundary",
                        "This materializes evaluation inputs and implements CPU response parsing/scoring; model generation and candidate-state admission remain separate implementation work"],
    }
    emit("data_manifest.json", (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode(), args.check)
    emit("evidence/data_audit.json", (json.dumps(report, indent=2, sort_keys=True) + "\n").encode(), args.check)
    print(json.dumps({"status": "verified" if args.check else "materialized", "files": {
        path: {key: value[key] for key in ("rows", "sha256", "max_ascii_prompt_chars")}
        for path, value in files.items()}}, indent=2))


if __name__ == "__main__":
    main()
