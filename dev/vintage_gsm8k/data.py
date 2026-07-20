"""Pure data handling and deterministic validation for Vintage GSM8K."""

from __future__ import annotations

import ast
import hashlib
import json
import os
import re
import tempfile
from collections import Counter, defaultdict
from decimal import Decimal, InvalidOperation
from fractions import Fraction
from pathlib import Path
from typing import Iterable

from .config import CUTOFF_YEAR, TOOL_TOKEN_FRAGMENTS


ANNOTATION_RE = re.compile(r"<<([^<>]+)>>")
FINAL_RE = re.compile(
    r"####\s*([+-]?(?:\d[\d,]*/\d[\d,]*|\d[\d,]*(?:\.\d+)?))(?=\s|$)"
)
NUMBER_RE = re.compile(r"(?<![A-Za-z])[-+]?\$?\d[\d,]*(?:\.\d+)?(?:/\d[\d,]*)?")
YEAR_RE = re.compile(r"\b(?:in|during|since|until|by|from|year|dated|born|opened|founded)\s+(\d{4})\b", re.I)
YEAR_SUFFIX_RE = re.compile(r"\b(\d{4})\s+(?:season|calendar year|school year)\b", re.I)


def stable_hash(value: object) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def parse_number(value: str) -> Fraction:
    cleaned = value.strip().replace(",", "").replace("$", "")
    if re.fullmatch(r"[+-]?\d+/\d+", cleaned):
        return Fraction(cleaned)
    try:
        return Fraction(Decimal(cleaned))
    except (InvalidOperation, ValueError, ZeroDivisionError) as exc:
        raise ValueError(f"not a numeric result: {value!r}") from exc


def _eval_ast(node: ast.AST) -> Fraction:
    if isinstance(node, ast.Expression):
        return _eval_ast(node.body)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return Fraction(str(node.value))
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
        value = _eval_ast(node.operand)
        return value if isinstance(node.op, ast.UAdd) else -value
    if isinstance(node, ast.BinOp):
        left, right = _eval_ast(node.left), _eval_ast(node.right)
        if isinstance(node.op, ast.Add):
            return left + right
        if isinstance(node.op, ast.Sub):
            return left - right
        if isinstance(node.op, ast.Mult):
            return left * right
        if isinstance(node.op, ast.Div):
            return left / right
        if isinstance(node.op, ast.Pow) and right.denominator == 1 and abs(right) <= 12:
            return left ** int(right)
    raise ValueError(f"unsupported arithmetic syntax: {ast.dump(node, include_attributes=False)}")


def evaluate_expression(expression: str) -> Fraction:
    cleaned = expression.replace(",", "").replace("$", "").strip()
    try:
        tree = ast.parse(cleaned, mode="eval")
    except SyntaxError as exc:
        raise ValueError(f"invalid arithmetic expression: {expression!r}") from exc
    return _eval_ast(tree)


def calculation_is_valid(expression: str, result: str) -> tuple[bool, str | None]:
    try:
        actual = evaluate_expression(expression)
        expected = parse_number(result)
    except ValueError as exc:
        return False, str(exc)
    if actual == expected:
        return True, None
    return False, f"{expression} evaluates to {actual}, not {result}"


def parse_calculator_annotations(answer: str) -> list[dict]:
    records = []
    for match in ANNOTATION_RE.finditer(answer):
        inner = match.group(1)
        if "=" not in inner:
            expression, result = inner, ""
            valid, error = False, "annotation has no '=' separator"
        else:
            expression, result = inner.rsplit("=", 1)
            valid, error = calculation_is_valid(expression, result)
        records.append(
            {
                "expression": expression.strip(),
                "result": result.strip(),
                "valid": valid,
                "error": error,
            }
        )
    return records


def normalize_answer(answer: str) -> str:
    """Remove calculator annotations while preserving their surrounding prose/results."""
    return re.sub(r"<<[^<>]+>>", "", answer)


def extract_final_answer(answer: str) -> str | None:
    matches = FINAL_RE.findall(answer)
    return matches[0].replace(",", "") if len(matches) == 1 else None


def final_answer_count(answer: str) -> int:
    return len(FINAL_RE.findall(answer))


def answers_equal(left: str | None, right: str | None) -> bool:
    if left is None or right is None:
        return False
    try:
        return parse_number(left) == parse_number(right)
    except ValueError:
        return left.strip().replace(",", "") == right.strip().replace(",", "")


def numeric_literals(text: str) -> list[str]:
    return [match.group(0).replace(",", "") for match in NUMBER_RE.finditer(text)]


def contextual_years(text: str) -> list[int]:
    matches = [int(value) for value in YEAR_RE.findall(text)]
    matches.extend(int(value) for value in YEAR_SUFFIX_RE.findall(text))
    return matches


def post_cutoff_years(text: str) -> list[int]:
    return [year for year in contextual_years(text) if year > CUTOFF_YEAR]


def validate_calculations(calculations: object) -> list[str]:
    errors = []
    if not isinstance(calculations, list):
        return ["calculations must be a JSON array"]
    for index, calculation in enumerate(calculations):
        if not isinstance(calculation, dict):
            errors.append(f"calculation {index} is not an object")
            continue
        expression = calculation.get("expression")
        result = calculation.get("result")
        if not isinstance(expression, str) or not isinstance(result, str):
            errors.append(f"calculation {index} must have string expression/result")
            continue
        valid, error = calculation_is_valid(expression, result)
        if not valid:
            errors.append(f"calculation {index}: {error}")
    return errors


def validate_candidate(source: dict, candidate: dict, mode: str) -> list[str]:
    errors: list[str] = []
    question, answer = candidate.get("question"), candidate.get("answer")
    if not isinstance(question, str) or not question.strip():
        errors.append("question must be a nonempty string")
    if not isinstance(answer, str) or not answer.strip():
        errors.append("answer must be a nonempty string")
    if errors:
        return errors
    combined = question + "\n" + answer
    if ANNOTATION_RE.search(combined):
        errors.append("candidate contains a <<calculator annotation>>")
    if any(fragment in combined for fragment in TOOL_TOKEN_FRAGMENTS):
        errors.append("candidate contains Python/tool tokens")
    if final_answer_count(answer) != 1 or extract_final_answer(answer) is None:
        errors.append("answer must contain exactly one parseable #### final answer")
    errors.extend(validate_calculations(candidate.get("calculations")))
    if mode == "surface":
        source_numbers = numeric_literals(source["question"] + "\n" + source["answer"])
        candidate_numbers = numeric_literals(combined)
        if candidate_numbers != source_numbers:
            errors.append("surface rewrite changed the ordered numeric literals")
        if not answers_equal(extract_final_answer(source["answer"]), extract_final_answer(answer)):
            errors.append("surface rewrite changed the final answer")
        source_calcs = [
            {"expression": item["expression"], "result": item["result"]}
            for item in source.get("calculations", [])
        ]
        if candidate.get("calculations") != source_calcs:
            errors.append("surface rewrite changed the source calculation sequence")
    elif mode == "date":
        remaining = post_cutoff_years(combined)
        if remaining:
            errors.append(f"date rewrite still contains post-1930 contextual years: {remaining}")
        if len(candidate.get("calculations", [])) != len(source.get("calculations", [])):
            errors.append("date rewrite changed the number of calculation steps")
    else:
        errors.append("rewrite mode must be 'surface' or 'date'")
    return errors


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Malformed JSONL at {path}:{line_number}: {exc}") from exc
            if not isinstance(value, dict):
                raise ValueError(f"Expected an object at {path}:{line_number}")
            rows.append(value)
    return rows


def read_latest_by_id(path: Path) -> dict[str, dict]:
    latest: dict[str, dict] = {}
    for row in read_jsonl(path):
        if isinstance(row.get("id"), str):
            latest[row["id"]] = row
    return latest


def atomic_write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def atomic_write_jsonl(path: Path, rows: Iterable[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def append_jsonl(path: Path, rows: Iterable[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def normalized_question(text: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", text.casefold()))


def cross_split_duplicates(train: list[dict], test: list[dict], threshold: float = 0.85) -> list[dict]:
    """Find exact and high-overlap cross-split questions without an O(n*m) scan."""
    train_norm = {row["id"]: normalized_question(row["question"]) for row in train}
    test_norm = {row["id"]: normalized_question(row["question"]) for row in test}
    exact: dict[str, list[str]] = defaultdict(list)
    for row_id, text in train_norm.items():
        exact[text].append(row_id)
    findings: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for test_id, text in test_norm.items():
        for train_id in exact.get(text, []):
            findings.append({"train_id": train_id, "test_id": test_id, "similarity": 1.0})
            seen.add((train_id, test_id))

    def shingles(value: str) -> set[tuple[str, ...]]:
        words = value.split()
        width = min(5, len(words))
        return {tuple(words[i : i + width]) for i in range(max(1, len(words) - width + 1))}

    train_shingles = {row_id: shingles(text) for row_id, text in train_norm.items()}
    index: dict[tuple[str, ...], list[str]] = defaultdict(list)
    for row_id, values in train_shingles.items():
        for value in values:
            index[value].append(row_id)
    for test_id, text in test_norm.items():
        values = shingles(text)
        overlap = Counter(train_id for value in values for train_id in index.get(value, []))
        for train_id, intersection in overlap.items():
            if (train_id, test_id) in seen:
                continue
            train_values = train_shingles[train_id]
            union = len(values) + len(train_values) - intersection
            similarity = intersection / union if union else 1.0
            if similarity >= threshold:
                findings.append(
                    {"train_id": train_id, "test_id": test_id, "similarity": round(similarity, 6)}
                )
    return findings
