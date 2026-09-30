"""Budget arithmetic for trusted runner receipts; not a runtime monitor.

The runner must supply every receipt created by the current candidate, verify
data lineage, and measure non-overlapping receipt durations. Candidate-written
logs are not evidence of compliance. This module does not establish those facts.
"""

import json
import math
from pathlib import Path


DEFAULT_LIMITS = Path(__file__).resolve().parents[1] / "configs" / "budget.json"


def _number(value, name, integer=False):
    permitted = (int,) if integer else (int, float)
    if type(value) not in permitted or not math.isfinite(value) or value < 0:
        raise ValueError(f"Invalid nonnegative {name}")
    return value


def account_candidate(candidate_id, current_work_elapsed_seconds,
                      distinct_training_states, student_token_exposures,
                      current_receipt_ids, used_data_receipt_ids, receipts,
                      limits=None):
    """Return numeric budget eligibility, conditional on trustworthy inputs.

    Receipts contain origin_candidate_id, parent_ids, generation_seconds,
    proposed_states, teacher_input_tokens and teacher_output_tokens. Reasoning
    tokens are part of output_tokens, not an additional double-counted field.
    All failures/retries/discarded requests belong in current_receipt_ids.
    """
    limits = limits or json.loads(DEFAULT_LIMITS.read_text())
    if not isinstance(candidate_id, str) or not candidate_id:
        raise ValueError("Candidate ID is required")
    elapsed = _number(current_work_elapsed_seconds, "current elapsed time")
    states = _number(distinct_training_states, "training state count", True)
    tokens = _number(student_token_exposures, "student exposure count", True)
    current = set(current_receipt_ids)
    expected_current = {key for key, receipt in receipts.items()
                        if receipt["origin_candidate_id"] == candidate_id}
    if current != expected_current:
        raise ValueError("Current receipt list is incomplete or has foreign receipts")
    closure, visiting = set(), set()

    def visit(receipt_id):
        if receipt_id in closure:
            return
        if receipt_id in visiting:
            raise ValueError("Cyclic receipt ancestry")
        if receipt_id not in receipts:
            raise ValueError("Missing receipt ancestor")
        visiting.add(receipt_id)
        receipt = receipts[receipt_id]
        for parent_id in receipt["parent_ids"]:
            visit(parent_id)
        for field in ("generation_seconds", "proposed_states",
                      "teacher_input_tokens", "teacher_output_tokens"):
            _number(receipt[field], field, field != "generation_seconds")
        if not isinstance(receipt["origin_candidate_id"], str) or not receipt["origin_candidate_id"]:
            raise ValueError("Receipt origin is required")
        visiting.remove(receipt_id)
        closure.add(receipt_id)

    for receipt_id in current | set(used_data_receipt_ids):
        visit(receipt_id)
    inherited = closure - current
    current_generation_seconds = sum(receipts[key]["generation_seconds"] for key in current)
    if current_generation_seconds > elapsed:
        raise ValueError("Exclusive current generation durations exceed current wall time")
    inherited_seconds = sum(receipts[key]["generation_seconds"] for key in inherited)
    charged_seconds = elapsed + inherited_seconds
    teacher_tokens = sum(receipts[key]["teacher_input_tokens"] + receipts[key]["teacher_output_tokens"]
                         for key in closure)
    attempts = sum(receipts[key]["proposed_states"] for key in closure)
    counts = {
        "candidate_production_charged_seconds": charged_seconds,
        "candidate_distinct_training_states": states,
        "candidate_proposed_state_attempts": attempts,
        "candidate_teacher_input_output_tokens": teacher_tokens,
        "candidate_student_nonpadding_token_exposures": tokens,
    }
    exceeded = [name for name, value in counts.items() if value > limits[name]]
    return {
        "numeric_budget_pass": not exceeded,
        "exceeded_limits": exceeded,
        "counts": counts,
        "current_work_elapsed_seconds": elapsed,
        "inherited_generation_seconds": inherited_seconds,
        "charged_receipt_ids": sorted(closure),
        "trusted_receipt_collection_verified": False,
        "trajectory_inherited_time_added": 0,
    }
