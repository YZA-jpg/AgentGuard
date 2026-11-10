import hashlib
import json
from collections import Counter
from collections.abc import Sequence
from pathlib import Path
from time import perf_counter
from typing import Any, TextIO

from .guard import Decision, Guard, GuardError, Review, Verdict, write_record


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


def read_split(path: Path) -> dict:
    split = json.loads(path.read_bytes())
    if split["config"] != "ATBench":
        raise ValueError("The split manifest must describe ATBench")
    groups = [list(map(str, split["splits"][name])) for name in ("train", "calibration", "heldout")]
    ids = [case_id for group in groups for case_id in group]
    if not all(groups) or len(ids) != len(set(ids)):
        raise ValueError("The split must have three nonempty, disjoint ID lists")
    return split


def recorded_candidate(raw: str) -> dict:
    try:
        action = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        action = None
    if isinstance(action, dict) and isinstance(action.get("name"), str) and "arguments" in action:
        return action
    return {"response": raw}


def replay_reviews(context: Review):
    task = None
    for index, message in enumerate(context.history):
        if message.get("role") == "user" and task is None:
            task = message.get("text") or message.get("content")
        if message.get("role") == "agent" and message.get("action"):
            candidate = recorded_candidate(message["action"])
            thought = message.get("thought")
            history = context.history[:index]
            if thought:
                history += ({"role": "agent", "thought": thought},)
            yield index, Review(history, task, candidate)


def run_atbench(guard: Guard, cases, output: TextIO, replay: bool = False) -> dict[str, Any]:
    counts: Counter = Counter()
    review_seconds = 0.0
    review_count = 0
    for case_id, label, context in cases:
        guard.reset()
        started = perf_counter()
        events = []
        try:
            verdict = Verdict(Decision.ALLOW)
            reviews = replay_reviews(context) if replay else [(None, context)]
            for index, review in reviews:
                review_started = perf_counter()
                verdict = guard.review(review)
                if verdict.decision == Decision.ERROR:
                    raise GuardError("Guard returned ERROR")
                elapsed = perf_counter() - review_started
                review_seconds += elapsed
                review_count += 1
                event = {
                    "event_index": index,
                    "decision": verdict.decision,
                    "risk_score": verdict.risk_score,
                    "latency_seconds": elapsed,
                }
                if verdict.details is not None:
                    event["details"] = verdict.details
                events.append(event)
                if verdict.decision in (Decision.HOLD, Decision.BLOCK):
                    break
            if not events:
                raise GuardError("No recorded actions were available to review")
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
            "guard_events": events,
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
        "successful_reviews": review_count,
        "mean_guard_latency_seconds": review_seconds / review_count if review_count else None,
    }
    write_record(output, summary)
    return summary
