"""Causal SafetyDrift inputs and a held-out split derived from the public release."""

import json
import random
from collections import defaultdict
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

import yaml

from .guard import Review, json_text
from .safetydrift import RELEASE, SOURCE, collect, original_split


@dataclass(frozen=True)
class SafetyCase:
    case_id: str
    category: str
    label: int
    first_hazard: int | None
    task: str
    tools: tuple
    steps: tuple

    @property
    def content_sha256(self):
        visible = {"task": self.task, "tools": self.tools, "steps": self.steps}
        return sha256(json.dumps(visible, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def adapt_case(case_id, trace, scenario):
    steps = []
    for raw in trace["steps"]:
        action = raw["action"]
        call = action.get("tool_call")
        candidate = ({"name": call["tool_name"], "arguments": call["arguments"]}
                     if call else {"response": action.get("raw_text", "")})
        steps.append({"candidate": candidate,
                      "thought": action.get("raw_text", "") if call else "",
                      "observation": raw["observation"]["content"]})
    first = next((i for i, step in enumerate(trace["steps"])
                  if step["safety_state_after"]["risk_level"] == 4), None)
    label = int(trace["metadata"]["reached_violation"])
    if bool(label) != (first is not None) or not steps:
        raise ValueError(f"Inconsistent SafetyDrift case: {case_id}")
    tools = tuple({k: t[k] for k in ("name", "description", "parameters") if k in t}
                  for t in scenario["tools"])
    return SafetyCase(case_id, trace["metadata"]["scenario_category"], label, first,
                      scenario["task_prompt"], tools, tuple(steps))


def reviews(case):
    history = ({"role": "user", "content": case.task},)
    for step in case.steps:
        prefix = history
        if step["thought"]:
            prefix += ({"role": "agent", "thought": step["thought"]},)
        yield Review(prefix, case.task, step["candidate"], case.tools)
        history += ({"role": "agent", "thought": step["thought"],
                     "action": json_text(step["candidate"])},
                    {"role": "environment", "content": step["observation"]})


def load_cases(root):
    root = Path(root)
    scenarios = {x["id"]: x for p in sorted((root / "scenarios").rglob("*.yaml"))
                 if (x := yaml.safe_load(p.read_bytes()))}
    inventory = collect(root)
    cases, discrepancies = [], []
    for item in inventory:
        trace = json.loads((root / item["path"]).read_bytes())
        case = adapt_case(item["path"], trace, scenarios[item["scenario_id"]])
        first_flag = next((i for i, s in enumerate(trace["steps"]) if s["is_violation_step"]), None)
        if first_flag != case.first_hazard:
            discrepancies.append(case.case_id)
        cases.append(case)
    source = {"traces": [(x["path"], x["sha256"]) for x in inventory],
              "scenarios": [(p.relative_to(root).as_posix(), sha256(p.read_bytes()).hexdigest())
                            for p in sorted((root / "scenarios").rglob("*.yaml"))]}
    return cases, inventory, sha256(json_text(source).encode()).hexdigest(), discrepancies


def development_split(cases, test_ids, seed=42):
    """Prioritize the fixed test set, deduplicate development content, then stratify."""
    test_ids = set(test_ids)
    heldout_hashes = {c.content_sha256 for c in cases if c.case_id in test_ids}
    seen, discarded, kept = set(), [], []
    for case in cases:
        if case.case_id in test_ids:
            continue
        key = case.content_sha256
        if key in heldout_hashes or key in seen:
            discarded.append(case.case_id)
        else:
            seen.add(key)
            kept.append(case)
    buckets = defaultdict(list)
    for case in kept:
        buckets[case.category, case.label].append(case.case_id)
    rng = random.Random(seed)
    train, calibration = [], []
    for key in sorted(buckets):
        ids = buckets[key][:]
        rng.shuffle(ids)
        n = max(1, round(len(ids) * .2))
        calibration.extend(ids[:n])
        train.extend(ids[n:])
    return train, calibration, discarded


def freeze_manifest(root, path):
    cases, inventory, source_hash, discrepancies = load_cases(root)
    _, test = original_split(inventory)
    test_ids = [x["path"] for x in test]
    train, calibration, discarded = development_split(cases, test_ids)
    lookup = {c.case_id: c for c in cases}
    splits = {"train": train, "calibration": calibration, "heldout": test_ids}
    manifest = {"id": "safetydrift-public-v1", "source": SOURCE, "revision": RELEASE,
                "source_sha256": source_hash, "seed": 42, "splits": splits,
                "duplicate_development_ids_removed": discarded,
                "author_test_preserved": True,
                "hazard_boundary": "first safety_state_after.risk_level == 4, matching author loader",
                "conflicting_is_violation_step_ids": discrepancies,
                "counts": {name: {"total": len(ids),
                                   "unsafe": sum(lookup[i].label for i in ids)}
                           for name, ids in splits.items()},
                "content_sha256": {c.case_id: c.content_sha256 for c in cases}}
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as out:
        json.dump(manifest, out, ensure_ascii=False, indent=2)
        out.write("\n")
    return manifest


def selected_cases(root, manifest_path, split="heldout"):
    cases, _, source_hash, _ = load_cases(root)
    manifest = json.loads(Path(manifest_path).read_bytes())
    if manifest["revision"] != RELEASE or manifest["source_sha256"] != source_hash:
        raise ValueError("SafetyDrift data does not match the frozen manifest")
    lookup = {c.case_id: c for c in cases}
    groups = list(manifest["splits"].values())
    ids = [i for group in groups for i in group]
    if len(ids) != len(set(ids)) or any(i not in lookup for i in ids):
        raise ValueError("Split IDs overlap or do not exist")
    hashes = [{lookup[i].content_sha256 for i in group} for group in groups]
    if any(hashes[i] & hashes[j] for i in range(len(hashes)) for j in range(i)):
        raise ValueError("Duplicate content crosses training/calibration/test splits")
    if any(lookup[i].content_sha256 != manifest["content_sha256"][i] for i in ids):
        raise ValueError("Case content changed")
    return [lookup[i] for i in manifest["splits"][split]], manifest
