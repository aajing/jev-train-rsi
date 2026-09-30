"""Strict CPU gate for completed responses against the frozen Judge dataset.

Run only from the task-owned Judge launcher. That launcher supplies --manifest
and --dataset from its trusted evaluation assets, NOT from candidate arguments
or a candidate-writable manifest. An optional manifest hash pins the manifest
itself when the launcher has a separately trusted hash. A hash in an untrusted
manifest would not establish trust. This module does not implement sandboxing.

For an official evaluation, the trusted Judge launcher must load the submitted
checkpoint, generate every response itself, and write --responses into its own
task-owned temporary directory (for example /task-owned/run/responses.jsonl).
Candidate-provided response files are NEVER accepted as final model results.
This CPU module can also consume text for offline tests, but cannot establish
which checkpoint produced it. Checkpoint identity and response provenance must
be verified by the outer launcher before the score can become official.

The dataset bytes must match the SHA256 in the manifest's fixed Judge entry.
The score is valid only for the complete 2800-row, 14-cell dataset and complete
ID-addressed responses. This CPU check does not run a GPU model or establish
resource/modification-scope eligibility. An outer trusted evaluator must check
those independently before publishing an eligible official score.

Responses are JSONL records with exactly {"id": <str>, "response": <str>}.
An empty or malformed completed response is wrong; an omitted response is an
incomplete evaluation and rejects the whole score. Output contains aggregates,
never hidden IDs, answers, or per-item results.
"""

from __future__ import annotations

import argparse
from collections import Counter
from collections.abc import Mapping
import hashlib
import json
from pathlib import Path
import re
import sys

from answer_protocol import DOMAIN_ORDER, is_scalar, score_completed_responses


JUDGE_KEY = "data/private/judge.jsonl"
REGIMES = ("id", "ood")
ROWS_PER_CELL = 200
TOTAL_ROWS = len(DOMAIN_ORDER) * len(REGIMES) * ROWS_PER_CELL
EXPECTED_CELLS = {(domain, regime): ROWS_PER_CELL
                  for domain in DOMAIN_ORDER for regime in REGIMES}


class JudgeValidationError(ValueError):
    """The frozen data or response set cannot receive a complete Judge score."""


def _unique_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise JudgeValidationError("Duplicate JSON object key")
        value[key] = item
    return value


def _reject_constant(value):
    raise JudgeValidationError("Nonstandard JSON constant")


def _json_loads(value):
    try:
        return json.loads(value, object_pairs_hook=_unique_object,
                          parse_constant=_reject_constant)
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise JudgeValidationError("Invalid JSON") from error


def _jsonl_rows(raw, label):
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as error:
        raise JudgeValidationError(label + " is not UTF-8") from error
    rows = []
    for line in text.splitlines():
        if not line.strip():
            raise JudgeValidationError(label + " contains an empty record")
        row = _json_loads(line)
        if not isinstance(row, dict):
            raise JudgeValidationError(label + " records must be JSON objects")
        rows.append(row)
    return rows


def _valid_hash(value):
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def load_frozen_dataset(dataset_path, manifest_path, *, manifest_sha256=None):
    """Load task-owned assets; callers, not this function, establish path trust.

    Returns (rows, dataset_sha256). Never use a candidate-supplied manifest to
    authorize candidate-supplied gold answers. Optional manifest_sha256 must
    come from a separately trusted launcher configuration to add protection.
    """
    manifest_raw = Path(manifest_path).read_bytes()
    if manifest_sha256 is not None:
        if not _valid_hash(manifest_sha256):
            raise JudgeValidationError("Invalid pinned manifest SHA256")
        if hashlib.sha256(manifest_raw).hexdigest() != manifest_sha256:
            raise JudgeValidationError("Manifest SHA256 mismatch")
    manifest = _json_loads(manifest_raw)
    try:
        entry = manifest["files"][JUDGE_KEY]
        expected_sha = entry["sha256"]
        expected_rows = entry["rows"]
        expected_counts = entry["by_domain_regime"]
    except (KeyError, TypeError) as error:
        raise JudgeValidationError("Missing frozen Judge manifest entry") from error
    if not _valid_hash(expected_sha):
        raise JudgeValidationError("Invalid frozen dataset SHA256")
    if type(expected_rows) is not int or expected_rows != TOTAL_ROWS:
        raise JudgeValidationError("Manifest must declare exactly 2800 Judge rows")
    manifest_cells = {domain + "/" + regime: count
                      for (domain, regime), count in EXPECTED_CELLS.items()}
    if (not isinstance(expected_counts, dict)
            or expected_counts != manifest_cells
            or any(type(count) is not int for count in expected_counts.values())):
        raise JudgeValidationError("Manifest must declare 200 rows in each of the 14 cells")

    dataset_raw = Path(dataset_path).read_bytes()
    dataset_sha = hashlib.sha256(dataset_raw).hexdigest()
    if dataset_sha != expected_sha:
        raise JudgeValidationError("Frozen Judge dataset SHA256 mismatch")
    if "bytes" in entry and (type(entry["bytes"]) is not int
                              or entry["bytes"] != len(dataset_raw)):
        raise JudgeValidationError("Frozen Judge dataset byte count mismatch")
    rows = _jsonl_rows(dataset_raw, "Judge dataset")
    if len(rows) != TOTAL_ROWS:
        raise JudgeValidationError("Frozen Judge dataset must contain exactly 2800 rows")
    ids, counts = set(), Counter()
    for row in rows:
        row_id = row.get("id")
        if not isinstance(row_id, str) or not row_id:
            raise JudgeValidationError("Every Judge row requires a nonempty string ID")
        if row_id in ids:
            raise JudgeValidationError("Duplicate Judge dataset ID")
        ids.add(row_id)
        domain, regime = row.get("domain"), row.get("regime")
        if not isinstance(domain, str) or not isinstance(regime, str):
            raise JudgeValidationError("Invalid Judge domain or regime")
        if (domain, regime) not in EXPECTED_CELLS:
            raise JudgeValidationError("Unexpected Judge domain or regime")
        counts[(domain, regime)] += 1
        if "answer" not in row or not is_scalar(row["answer"]):
            raise JudgeValidationError("Judge gold answer must be a permitted JSON scalar")
    if counts != EXPECTED_CELLS:
        raise JudgeValidationError("Judge dataset requires exactly 200 rows in every cell")
    return rows, dataset_sha


def load_responses(path):
    """Preserve JSONL entries until duplicate and ID-set checks have completed."""
    return _jsonl_rows(Path(path).read_bytes(), "Responses")


def _align_responses(rows, responses):
    if isinstance(responses, Mapping):
        items = [{"id": row_id, "response": response}
                 for row_id, response in responses.items()]
    elif isinstance(responses, (list, tuple)):
        items = responses
    else:
        raise JudgeValidationError("Responses require an ID mapping or ID-addressed records")
    by_id = {}
    for item in items:
        if not isinstance(item, Mapping) or set(item) != {"id", "response"}:
            raise JudgeValidationError("Every response record requires exactly id and response")
        row_id = item["id"]
        if not isinstance(row_id, str) or not row_id:
            raise JudgeValidationError("Response ID must be a nonempty string")
        if row_id in by_id:
            raise JudgeValidationError("Duplicate response ID")
        if not isinstance(item["response"], str):
            raise JudgeValidationError("Every completed response must be text")
        by_id[row_id] = item["response"]
    expected_ids = {row["id"] for row in rows}
    if set(by_id) != expected_ids:
        raise JudgeValidationError("Response IDs must match all 2800 frozen Judge IDs exactly")
    return [by_id[row["id"]] for row in rows]


def score_frozen_judge(dataset_path, manifest_path, responses, *, manifest_sha256=None):
    """CPU score of supplied text; provenance and eligibility remain external.

    Official use requires responses generated by the trusted Judge launcher
    directly from the submitted checkpoint. Candidate-supplied answers are not
    a valid final submission, even if they pass every CPU completeness check.
    """
    rows, dataset_sha = load_frozen_dataset(
        dataset_path, manifest_path, manifest_sha256=manifest_sha256)
    aligned = _align_responses(rows, responses)
    result = score_completed_responses(rows, aligned)
    # All cells have equal size, so use the exact official micro count formula.
    # Do not round: one wrong response must not be presented as a full score.
    result["score"] = 100 * result["correct"] / TOTAL_ROWS
    result.update(dataset_sha256=dataset_sha,
                  data_integrity_verified=True,
                  responses_complete=True,
                  response_provenance_verified=False,
                  eligibility_checked=False,
                  eligibility_note="Checkpoint identity, Judge-generated response provenance, GPU execution, resource budget and modification scope require outer Judge checks")
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", required=True,
                        help="Task-owned Judge dataset path supplied by the trusted launcher")
    parser.add_argument("--manifest", required=True,
                        help="Task-owned frozen manifest path; must not be candidate-controlled")
    parser.add_argument("--manifest-sha256", help="Optional separately trusted manifest SHA256 pin")
    parser.add_argument("--responses", required=True,
                        help="Task-owned JSONL of responses generated by the trusted Judge launcher from the submitted checkpoint; never a candidate-provided response file. Exactly id and response fields per row.")
    args = parser.parse_args(argv)
    try:
        result = score_frozen_judge(args.dataset, args.manifest,
                                    load_responses(args.responses),
                                    manifest_sha256=args.manifest_sha256)
    except (JudgeValidationError, OSError) as error:
        # Data validation errors are deliberately generic and reveal no gold rows.
        print(json.dumps({"scored": False, "error": str(error)}), file=sys.stderr)
        return 2
    print(json.dumps({"scored": True, **result}, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
