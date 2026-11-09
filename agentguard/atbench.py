import hashlib
import json
from collections import Counter
from collections.abc import Sequence
from pathlib import Path
from time import perf_counter
from typing import Any, TextIO

from .guard import Decision, Guard, GuardError, Review, write_record


def read_rows(path: Path, config: str, case_ids: Sequence[str], limit: int | None):
    raw = path.read_bytes()
    rows = json.loads(raw)
    if not isinstance(rows, list):
        raise ValueError("ATBench input must be an official JSON array")
    id_field, history_field = ("id", "contents") if config == "ATBench" else ("conv_id", "content")
    keys = [str(row[id_field]) for row in rows]
    if len(set(keys)) != len(keys):
        raise ValueError("Duplicate ATBench IDs")
    if missing := set(case_ids) - set(keys):
        raise ValueError(f"Unknown case IDs: {sorted(missing)}")
    selected = []
    for row in rows:
        case_id = str(row[id_field])
        if case_ids and case_id not in case_ids:
            continue
        if row["label"] not in (0, 1):
            raise ValueError(f"Invalid binary label for {case_id}")
        history = tuple(message for group in row[history_field] for message in group)
        selected.append((case_id, int(row["label"]), Review(history)))
    if not selected:
        raise ValueError("No ATBench cases selected")
    return hashlib.sha256(raw).hexdigest(), selected[:limit]


def run_atbench(guard: Guard, cases, output: TextIO) -> dict[str, Any]:
    counts: Counter = Counter()
    for case_id, label, context in cases:
        guard.reset()
        started = perf_counter()
        try:
            verdict = guard.review(context)
            if verdict.decision == Decision.ERROR:
                raise GuardError("Guard returned ERROR")
            prediction = int(verdict.decision in (Decision.HOLD, Decision.BLOCK))
            counts[label, prediction] += 1
            record = {
                "status": "ok",
                "prediction": prediction,
                "decision": verdict.decision,
                "risk_score": verdict.risk_score,
            }
        except GuardError as error:
            counts["error"] += 1
            record = {"status": "guard_error", "error": str(error)}
        write_record(output, {
            "record_type": "case",
            "case_id": case_id,
            "label": label,
            "guard_latency_seconds": perf_counter() - started,
            **record,
        })

    tn, fp, fn, tp = (counts[key] for key in ((0, 0), (0, 1), (1, 0), (1, 1)))
    scored = tn + fp + fn + tp

    def ratio(numerator: int, denominator: int) -> float | None:
        return numerator / denominator if denominator else None

    summary = {
        "record_type": "overall_summary",
        "total_cases": scored + counts["error"],
        "completed_cases": scored,
        "error_cases": counts["error"],
        "tp": tp,
        "fp": fp,
        "tn": tn,
        "fn": fn,
        "accuracy": ratio(tp + tn, scored),
        "f1": ratio(2 * tp, 2 * tp + fp + fn),
        "recall": ratio(tp, tp + fn),
        "fpr": ratio(fp, fp + tn),
    }
    write_record(output, summary)
    return summary
