"""Fixed free-response protocol and CPU scoring helpers; no model evaluator.

The GPU generation wrapper and candidate-state admission validator remain
future task packaging. These helpers score already completed textual responses.
"""

from __future__ import annotations

import ast
from datetime import datetime, timezone
import json
import operator
import re


FINAL_PREFIX = "Final answer:"
PROMPT_INSTRUCTION = (
    "Solve the problem using only the supplied state and rules. You may explain your reasoning.\n"
    "End with exactly one line in this format: Final answer: <JSON scalar>\n"
    "The scalar must be a JSON boolean, integer, or quoted string, as appropriate for the question.\n"
    "Do not use a float, null, array, or object. Do not write the final-answer prefix anywhere else."
)
DOMAIN_ORDER = (
    "formal_logic", "relations", "arithmetic", "temporal", "code_semantics",
    "algorithms", "evidence_integration",
)


class AnswerFormatError(ValueError):
    """A completed model response does not obey the fixed answer protocol."""


def is_scalar(value):
    return type(value) in (bool, int, str)


def typed_equal(left, right):
    return is_scalar(left) and type(left) is type(right) and left == right


def _reject_constant(value):
    raise AnswerFormatError("Nonstandard JSON constants are not allowed")


def parse_response(response):
    if not isinstance(response, str):
        raise AnswerFormatError("Response must be text")
    # Count exact prefixes everywhere, including reasoning and quoted content.
    if response.count(FINAL_PREFIX) != 1:
        raise AnswerFormatError("Exactly one final-answer prefix is required")
    lines = [line for line in response.splitlines() if line.strip()]
    if not lines or not lines[-1].startswith(FINAL_PREFIX + " "):
        raise AnswerFormatError("The last nonempty line must be the final-answer line")
    payload = lines[-1][len(FINAL_PREFIX) + 1:]
    try:
        value = json.loads(payload, parse_constant=_reject_constant)
    except (json.JSONDecodeError, ValueError) as error:
        raise AnswerFormatError("Final answer is not one complete permitted JSON scalar") from error
    if not is_scalar(value):
        raise AnswerFormatError("Final answer must be a boolean, integer, or string")
    return value


def format_answer(answer):
    if not is_scalar(answer):
        raise ValueError("Gold answer must be a permitted JSON scalar")
    return FINAL_PREFIX + " " + json.dumps(answer, ensure_ascii=True, allow_nan=False)


def response_correct(response, answer):
    try:
        return typed_equal(parse_response(response), answer)
    except AnswerFormatError:
        return False


def render_ascii_prompt(row):
    # Only state/question enter from the record; the instruction is constant.
    state = json.dumps(row["state"], ensure_ascii=True, sort_keys=True,
                       separators=(",", ":"), allow_nan=False)
    question = json.dumps(row["question"], ensure_ascii=True, allow_nan=False)
    return PROMPT_INSTRUCTION + "\n[state] " + state + "\n[question] " + question + "\n[response]"


def score_completed_responses(rows, responses):
    """Generic diagnostic scorer; this is NOT the frozen official Judge gate.

    It intentionally accepts smaller development fixtures with nonempty cells.
    A 100 here is only the accuracy of those supplied rows. For the official
    2800-row dataset/hash/ID-completeness checks, use judge_gate.score_frozen_judge.
    Callers must separately validate candidate eligibility and generation completion.
    Missing responses are an incomplete evaluation, not ordinary wrong answers.
    """
    if len(rows) != len(responses):
        raise ValueError("Incomplete evaluation")
    cells = {(domain, regime): [] for domain in DOMAIN_ORDER for regime in ("id", "ood")}
    for row, response in zip(rows, responses):
        cells[(row["domain"], row["regime"])].append(response_correct(response, row["answer"]))
    if any(not values for values in cells.values()):
        raise ValueError("Every domain and regime requires evaluated states")
    rates = {key: sum(values) / len(values) for key, values in cells.items()}
    condition = {regime: sum(rates[(d, regime)] for d in DOMAIN_ORDER) / 7 for regime in ("id", "ood")}
    return {"score": 100 * (condition["id"] + condition["ood"]) / 2,
            "id_accuracy": condition["id"], "ood_accuracy": condition["ood"],
            "correct": sum(sum(values) for values in cells.values()), "total": len(rows),
            "all_answers_correct": all(all(values) for values in cells.values())}


def _boolean_value(expression, assignments):
    tokens = re.findall(r"[A-Za-z_][A-Za-z_0-9]*|[()]", expression)
    if re.sub(r"\s+", "", expression) != "".join(tokens):
        raise ValueError("Unexpected Boolean syntax")
    position = 0

    def parse():
        nonlocal position
        token = tokens[position]
        position += 1
        if token == "NOT":
            if tokens[position] != "(":
                raise ValueError("Missing parenthesis")
            position += 1
            value = not parse()
            if tokens[position] != ")":
                raise ValueError("Missing parenthesis")
            position += 1
            return value
        if token == "(":
            left = parse()
            op = tokens[position]
            position += 1
            right = parse()
            if tokens[position] != ")":
                raise ValueError("Missing parenthesis")
            position += 1
            return {"AND": left and right, "OR": left or right,
                    "XOR": left != right, "IMPLIES": not left or right}[op]
        value = assignments[token]
        if type(value) is not bool:
            raise ValueError("Non-Boolean assignment")
        return value

    result = parse()
    if position != len(tokens):
        raise ValueError("Trailing Boolean expression")
    return result


_OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
        ast.FloorDiv: operator.floordiv, ast.Mod: operator.mod}


def _expression(node, values):
    if isinstance(node, ast.Constant) and type(node.value) is int:
        return node.value
    if isinstance(node, ast.Name):
        return values[node.id]
    if isinstance(node, ast.List):
        return [_expression(item, values) for item in node.elts]
    if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
        return _OPS[type(node.op)](_expression(node.left, values), _expression(node.right, values))
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
        value = _expression(node.operand, values)
        return -value if isinstance(node.op, ast.USub) else value
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and not node.keywords:
        return {"abs": abs, "min": min, "max": max}[node.func.id](*[_expression(x, values) for x in node.args])
    if isinstance(node, ast.Compare) and len(node.ops) == 1:
        compare = {ast.Gt: operator.gt, ast.Eq: operator.eq}
        return compare[type(node.ops[0])](_expression(node.left, values), _expression(node.comparators[0], values))
    raise ValueError("Unsupported expression")


def _program(source):
    values = {}

    def run(statements):
        for node in statements:
            if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
                values[node.targets[0].id] = _expression(node.value, values)
            elif isinstance(node, ast.AugAssign) and isinstance(node.target, ast.Name):
                values[node.target.id] = _OPS[type(node.op)](values[node.target.id], _expression(node.value, values))
            elif isinstance(node, ast.For) and isinstance(node.target, ast.Name) and not node.orelse:
                for item in _expression(node.iter, values):
                    values[node.target.id] = item
                    run(node.body)
            elif isinstance(node, ast.If):
                run(node.body if _expression(node.test, values) else node.orelse)
            else:
                raise ValueError("Unsupported statement")
    run(ast.parse(source).body)
    if type(values["result"]) is not int:
        raise ValueError("Non-integer program result")
    return values["result"]


def oracle_answer(row):
    """Independent label recomputation for source-derived states, not admission.

    These evaluators consume normalized state/question without options, answer,
    source labels, upstream oracle calls, eval, or exec. They intentionally are
    not a full schema/range or resource-safety validator for arbitrary proposals.
    """
    state, domain = row["state"], row["domain"]
    if domain == "formal_logic":
        return _boolean_value(state["expression"], state["assignments"])
    if domain == "relations":
        start, goal = state["start"], state["goal"]
        if [start, goal] in state["directed_edges"] or (start, goal) in state["directed_edges"]:
            return "direct"
        reached = {start}
        while True:
            more = reached | {b for a, b in state["directed_edges"] if a in reached}
            if more == reached:
                return "indirect" if goal in reached else "unreachable"
            reached = more
    if domain == "arithmetic":
        return _expression(ast.parse(state["expression"], mode="eval").body, state["values"])
    if domain == "temporal":
        latest = "latest" in row["question"]
        selected = (max if latest else min)(state["events"], key=lambda event: (
            datetime.fromisoformat(event["timestamp"]).astimezone(timezone.utc), event["id"]))
        return selected["id"]
    if domain == "code_semantics":
        return _program(state["source"])
    if domain == "algorithms":
        values = sorted([x for x in state["values"] if x % state["divisor"] == 0],
                        reverse=state["order"] == "descending")
        index = state["zero_based_index"]
        return values[index] if index < len(values) else "not_present"
    if domain == "evidence_integration":
        def canonical(name):
            seen = set()
            while name in state["aliases"]:
                if name in seen:
                    raise ValueError("Cyclic alias")
                seen.add(name)
                name = state["aliases"][name]
            return name
        valid = [record for record in state["records"] if record["authoritative"] and not record["retracted"]
                 and canonical(record["entity"]) == canonical(state["query_entity"])
                 and record["property"] == state["query_property"]]
        if not valid:
            return "not_stated"
        highest = max(record["revision"] for record in valid)
        values = {record["value"] for record in valid if record["revision"] == highest}
        return next(iter(values)) if len(values) == 1 else "conflict"
    raise ValueError("Unknown domain")
