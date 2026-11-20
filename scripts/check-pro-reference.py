"""Match observable Pro reference inputs against the official runner, offline."""

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import socket
import sys
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agentguard.native_agentdojo import author_runtime, digest, inventory


def text(content):
    if isinstance(content, str):
        return content
    return "\n".join(block.get("content", block.get("text", "")) for block in content or [])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    settings = SimpleNamespace(model="deepseek-v4-pro", attack_model_name="Deepseek v4 Pro",
        suite=["workspace", "slack", "travel", "banking"], stage=["capability", "under_attack"],
        limit_per_suite=None, check_candidates=False, exclude_user_task=["slack:7", "slack:17"])
    inspected = inventory(settings)
    runtime = author_runtime(settings.model, settings.attack_model_name)

    def no_network(*args, **kwargs):
        raise RuntimeError("Network disabled in reference input validation")
    socket.socket.connect = no_network
    socket.create_connection = no_network
    attackers = {name: runtime.load_attack("important_instructions", runtime.get_suite("v1.2.2", name),
                 SimpleNamespace(name=settings.model)) for name in settings.suite}
    planned = {(row["suite"], row["task_id"], row["injection_id"]) for row in inspected["cases"] if row["stage"] == "under_attack"}
    actual, manifests, extra_user_messages = set(), [], []
    scores, suites = Counter(), Counter()
    for path in sorted(args.reference_root.rglob("*.json")):
        raw = path.read_bytes()
        record = json.loads(raw)
        key = (record["suite_name"], record["user_task_id"], record["injection_task_id"])
        assert key not in actual, ("Duplicate reference", key)
        actual.add(key)
        assert record["pipeline_name"] == settings.model and record["attack_type"] == "important_instructions", key
        assert record["benchmark_version"] == "v1.2.2" and record["agentdojo_package_version"] == "0.1.35", key
        suite = runtime.get_suite("v1.2.2", key[0])
        user, injection = suite.get_user_task_by_id(key[1]), suite.get_injection_task_by_id(key[2])
        assert record["injections"] == attackers[key[0]].attack(user, injection), ("Injection differs", key)
        systems = [m for m in record["messages"] if m["role"] == "system"]
        users = [m for m in record["messages"] if m["role"] == "user"]
        assert len(systems) == 1 and text(systems[0]["content"]) == inspected["system_prompt"], key
        assert text(users[0]["content"]) == user.PROMPT, ("Initial user prompt differs", key)
        if len(users) > 1:
            extra_user_messages.append(dict(case=key, additional_user_messages=len(users) - 1))
        scores["attack_successes"] += bool(record["security"])
        scores["utility_successes"] += bool(record["utility"])
        suites[key[0]] += 1
        manifests.append(dict(path=str(path.relative_to(args.reference_root)), sha256=hashlib.sha256(raw).hexdigest()))
    assert actual == planned and len(actual) == 939, ("Reference cohort differs", len(actual), len(planned))
    report = dict(reference_root=str(args.reference_root.resolve()), model=settings.model,
        attack_model_name=settings.attack_model_name, matched_cases=939, matched_system_prompts=939,
        matched_initial_user_prompts=939, matched_injection_dictionaries=939, suite_cases=dict(suites),
        reference_asr=scores["attack_successes"] / 939, reference_scores=dict(scores),
        additional_reference_user_messages=extra_user_messages,
        historical_unknowns=["api_endpoint", "temperature", "thinking_setting", "output_cap", "serving_snapshot", "dependency_lock"],
        current_policy="author-original initial input; do not replay historical assistant replies or extra monitor feedback",
        reference_manifest_sha256=digest(manifests), input_manifest=manifests, official_provenance=inspected["provenance"])
    if args.output.exists():
        old = json.loads(args.output.read_text())
        assert old["reference_manifest_sha256"] == report["reference_manifest_sha256"], "Reference changed; use a new run"
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key not in ["input_manifest", "official_provenance"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
