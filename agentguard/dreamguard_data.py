"""Explicit pre-action inputs and independently verified dataset partitions."""

import json
from hashlib import sha256


def json_text(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def fingerprint(value):
    return sha256(json_text(value).encode()).hexdigest()


def source_examples(root, split_path):
    from .safetydrift_data import selected_cases

    examples = []
    for split in ("train", "calibration", "heldout"):
        cases, manifest = selected_cases(root, split_path, split)
        for case in cases:
            successors = [step["observation"] for step in case.steps]
            examples.append({"id": case.case_id, "dataset": "safetydrift", "split": split,
                             "task": case.task, "observations": [""] + successors[:-1],
                             "actions": [json_text(s["candidate"]) for s in case.steps],
                             "successors": successors, "label": case.label,
                             "first_hazard": case.first_hazard})
    examples, discarded, test_duplicates = projection_deduplicate(examples)
    verify_examples(examples)
    manifest = {**manifest, "base_counts": manifest["counts"],
                "counts": {name: {"total": sum(r["split"] == name for r in examples),
                                  "unsafe": sum(r["split"] == name and r["label"] for r in examples)}
                           for name in ("train", "calibration", "heldout")},
                "projection_duplicates_removed": discarded,
                "within_test_duplicate_inputs": test_duplicates}
    return examples, manifest


def input_fingerprint(row):
    # These are the actual classifier inputs. Tool schemas/thoughts/post-action
    # targets are omitted by this reproduction and cannot distinguish two cases.
    return fingerprint([row["task"], row["observations"], row["actions"]])


def projection_deduplicate(rows):
    """Preserve every author test ID; remove development copies of visible input."""
    seen, discarded, test_duplicates, kept = {}, [], [], set()
    for split in ("heldout", "calibration", "train"):
        for row in rows:
            if row["split"] != split:
                continue
            key = (row["dataset"], input_fingerprint(row))
            prior = seen.get(key)
            audit = {"id": row["id"], "split": split,
                     "kept_id": prior["id"] if prior else None,
                     "label_conflict": prior is not None and prior["label"] != row["label"]}
            if prior is not None and split != "heldout":
                discarded.append(audit)
                continue
            if prior is not None:
                test_duplicates.append(audit)
            seen[key] = row
            kept.add((row["dataset"], row["id"]))
    return [r for r in rows if (r["dataset"], r["id"]) in kept], discarded, test_duplicates


def target_examples(path, split_path=None):
    from .atbench import read_rows, read_split, replay_reviews
    from .traces import content_text

    split = read_split(split_path) if split_path else None
    ids = list(map(str, split["splits"]["heldout"])) if split else []
    digest, rows = read_rows(path, "ATBench", ids, None)
    if split and digest != split["source_sha256"]:
        raise ValueError("ATBench data does not match frozen split")
    examples = []
    for case_id, label, context in rows:
        observations, actions, task = [], [], None
        for _, review in replay_reviews(context):
            task = review.task
            observations.append(next((content_text(m.get("content")) for m in reversed(review.history)
                                      if m["role"] in ("tool", "environment")), ""))
            candidate = review.candidate
            action = ({"name": candidate["name"], "arguments": candidate["arguments"]}
                      if "name" in candidate else {"response": candidate["response"]})
            actions.append(json_text(action))
        examples.append({"id": str(case_id), "dataset": "atbench", "split": "heldout", "task": task,
                         "observations": observations, "actions": actions, "successors": [],
                         "label": label, "first_hazard": None})
    verify_examples(examples)
    return examples


def verify_examples(rows):
    keys, contents = set(), {}
    for row in rows:
        key = (row["dataset"], row["id"])
        if key in keys:
            raise ValueError(f"Repeated case ID: {key}")
        keys.add(key)
        count = len(row["actions"])
        if count < 1 or len(row["observations"]) != count or row["label"] not in (0, 1):
            raise ValueError(f"Malformed sequence: {key}")
        if row["successors"] and len(row["successors"]) != count:
            raise ValueError(f"Successor length differs: {key}")
        first = row["first_hazard"]
        if first is not None and (row["label"] != 1 or not 0 <= first < count):
            raise ValueError(f"Invalid hazard annotation: {key}")
        digest = input_fingerprint(row)
        group = (row["dataset"], row["split"])
        if digest in contents and contents[digest] != group:
            raise ValueError("Identical content crosses data partitions")
        contents[digest] = group
