"""Inventory SafetyDrift and freeze the public release's original split."""

import argparse
import json
import random
from collections import Counter, defaultdict
from hashlib import sha256
from pathlib import Path

RELEASE = "5c55e54b75c9c7ee2037db8f3dbd6ae6a7dab8a8"
SOURCE = "aditya593/SafetyDrift-traces"


def collect(root):
    cases = []
    for path in sorted((root / "traces").rglob("*.json")):
        raw = path.read_bytes()
        trace = json.loads(raw)
        metadata = trace["metadata"]
        steps = trace["steps"]
        first_violation = next(
            (step["step_index"] for step in steps if step["safety_state_after"]["risk_level"] == 4), None,
        )
        reached_violation = metadata["reached_violation"]
        if not isinstance(reached_violation, bool) or reached_violation != (first_violation is not None):
            raise ValueError(f"Inconsistent violation annotation: {path.relative_to(root)}")
        cases.append({
            "path": path.relative_to(root).as_posix(),
            "sha256": sha256(raw).hexdigest(),
            "scenario_id": metadata["scenario_id"],
            "category": metadata["scenario_category"],
            "reached_violation": reached_violation,
            "first_violation_step_index": first_violation,
            "steps": len(steps),
        })
    if len(cases) != 357:
        raise ValueError(f"Expected 357 traces in the pinned public release, found {len(cases)}")
    return cases


def original_split(cases):
    """Match the source loader's ordering, strata and per-stratum rounding."""
    buckets = defaultdict(list)
    for case in cases:
        buckets[case["category"], case["reached_violation"]].append(case)
    rng = random.Random(42)
    train, test = [], []
    for key in sorted(buckets):
        group = buckets[key]
        rng.shuffle(group)
        cutoff = max(1, round(len(group) * 0.2))
        test.extend(group[:cutoff])
        train.extend(group[cutoff:])
    return train, test


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    cases = collect(args.data_root)
    train, test = original_split(cases)
    if (len(train), len(test)) != (285, 72):
        raise ValueError(f"Unexpected split totals: {len(train)} train, {len(test)} test")
    summary = {
        "traces": len(cases), "steps": sum(case["steps"] for case in cases),
        "unsafe": sum(case["reached_violation"] for case in cases),
        "by_category": dict(Counter(case["category"] for case in cases)),
        "train": len(train), "test": len(test),
    }
    manifest = {
        "source": SOURCE, "revision": RELEASE, "protocol": "safetydrift_public_original",
        "seed": 42, "test_fraction": 0.2, "summary": summary, "train": train, "test": test,
    }
    with args.output.open("x", encoding="utf-8") as output:
        json.dump(manifest, output, indent=2)
        output.write("\n")
    print(json.dumps(summary))


if __name__ == "__main__":
    main()
