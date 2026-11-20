"""Frozen 40-case Flash/Pro diagnostic; invoke only with user authorization."""

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import random
import subprocess
import sys
from types import SimpleNamespace

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from agentguard import native_agentdojo as native

CONDITIONS = (
    dict(name="A_flash_t0", model="deepseek-v4-flash-0731", temperature=0.0),
    dict(name="B_pro_t0", model="deepseek-v4-pro", temperature=0.0),
    dict(name="C_pro_default", model="deepseek-v4-pro", temperature=None),
)
CANARY = dict(stage="under_attack", suite="workspace", task_id="user_task_0", injection_id="injection_task_0")


def select_cases(records, seed=42):
    """Uniformly sample within suites, without consulting success labels."""
    rng, selected = random.Random(seed), []
    for suite in native.SUITES:
        pool = sorted((case for case in records if case["suite"] == suite),
                      key=lambda case: (native.number(case["task_id"]), native.number(case["injection_id"])))
        selected.extend(rng.sample(pool, 10))
    return sorted(selected, key=lambda case: (native.SUITES.index(case["suite"]),
                  native.number(case["task_id"]), native.number(case["injection_id"])))


def condition_args(condition, output, workers, resume=False):
    return SimpleNamespace(model=condition["model"], temperature=condition["temperature"],
        attack_model_name="DeepSeek", thinking="enabled", max_tokens=None, system_role="system",
        suite=list(native.SUITES), stage=["under_attack"], exclude_user_task=[], limit_per_suite=None,
        check_candidates=False, workers=workers, timeout=180.0, case_attempts=2,
        env_file=PROJECT / ".env", output=output, resume=resume)


def load_reference(root):
    records, hashes = {}, []
    for path in sorted(root.rglob("*.json")):
        raw = path.read_bytes()
        row = json.loads(raw)
        assert row["pipeline_name"] == "deepseek-v4-pro" and row["attack_type"] == "important_instructions"
        case = dict(stage="under_attack", suite=row["suite_name"], task_id=row["user_task_id"], injection_id=row["injection_task_id"])
        key = native.case_key(case)
        assert key not in records
        records[key] = dict(case=case, reference_security=bool(row["security"]), path=str(path.relative_to(root)))
        hashes.append(dict(path=str(path.relative_to(root)), sha256=hashlib.sha256(raw).hexdigest()))
    assert len(records) == 939
    return records, native.digest(hashes)


def prepare(root, workers):
    references, source_hash = load_reference(root)
    selected = select_cases([row["case"] for row in references.values()])
    inspections, signatures = {}, {}
    for condition in CONDITIONS:
        args = condition_args(condition, Path("unused"), workers)
        inspected = native.inventory(args)
        available = {native.case_key(case) for case in inspected["cases"]}
        assert all(native.case_key(case) in available for case in [*selected, CANARY])
        runtime = native.author_runtime(args.model, args.attack_model_name)
        fingerprints = {}
        for case in [*selected, CANARY]:
            suite = runtime.get_suite("v1.2.2", case["suite"])
            user = suite.get_user_task_by_id(case["task_id"])
            attacker = runtime.load_attack("important_instructions", suite, SimpleNamespace(name=args.model))
            injections = attacker.attack(user, suite.get_injection_task_by_id(case["injection_id"]))
            fingerprints[native.case_key(case)] = native.digest(dict(user=user.PROMPT, injections=injections))
        signatures[condition["name"]] = native.digest(dict(system=inspected["system_prompt_sha256"],
            tools=inspected["tool_schema_sha256"], cases=fingerprints))
        inspections[condition["name"]] = inspected
    assert len(set(signatures.values())) == 1, "Input differs across conditions"
    identity = dict(seed=42, cases=selected, conditions=list(CONDITIONS), workers=workers,
        common_request_settings=dict(thinking="enabled", attack_model_name="DeepSeek", max_tokens=None, system_role="system"),
        reference_manifest_sha256=source_hash, input_signatures=signatures,
        controller_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        native_runner_sha256=hashlib.sha256((PROJECT / "agentguard/native_agentdojo.py").read_bytes()).hexdigest(),
        reference_successes_in_selected_cases=sum(references[native.case_key(case)]["reference_security"] for case in selected),
        sampling_note="Ten uniformly sampled cases per suite, seed 42; selection ignores outcomes. Diagnostic only, not a full-benchmark ASR estimate.")
    return identity, inspections


def execute(condition, directory, cases, inspected, workers):
    args = condition_args(condition, directory, workers, resume=directory.exists())
    subset = {**inspected, "cases": cases}
    result = native.run(args, subset)
    if result:
        raise RuntimeError(f"Condition failed: {condition['name']}; inspect preserved API error codes before proceeding")
    subprocess.run([sys.executable, str(PROJECT / "scripts/verify-official-dojo.py"), str(directory)], check=True, cwd=PROJECT)


def audit_condition(directory, expected_model):
    rows = {row["case_key"]: row for row in native.read_records(directory / "cases.jsonl")}
    counts, models, finish = Counter(), Counter(), Counter()
    for row in rows.values():
        for event in native.read_records(Path(row["api_log"])):
            request = event["request"]
            assert request.get("extra_body", {}).get("enable_thinking") is True
            assert "max_tokens" not in request
            counts["api_calls"] += 1
            if "response" in event:
                response = event["response"]
                model = response.get("model", "unknown")
                assert model.lower().startswith(expected_model.lower()), ("Unexpected served model", model, expected_model)
                models[model] += 1
                counts["reasoning_tokens"] += ((response.get("usage") or {}).get("completion_tokens_details") or {}).get("reasoning_tokens", 0) or 0
                for choice in event["response"].get("choices", []):
                    finish[choice.get("finish_reason", "unknown")] += 1
                    counts["responses_with_reasoning"] += bool((choice["message"].get("reasoning_content") or "").strip())
        if row["suite"] == "travel" and row["injection_task_id"] == 6 and row["attack_success"]:
            counts["travel_keyword_checker_successes_needing_content_review"] += 1
    return rows, dict(**counts, response_models=dict(models), finish_reasons=dict(finish))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--reference-root", type=Path, default=PROJECT / "deepseek_result")
    parser.add_argument("--workers", type=native.positive, default=4)
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    output = args.output.resolve()
    identity, inspections = prepare(args.reference_root, args.workers)
    if output.exists():
        if not args.resume:
            raise RuntimeError("Output exists; use a new directory or --resume")
        assert json.loads((output / "experiment.json").read_text())["identity"] == identity, "Frozen diagnostic changed"
    else:
        output.mkdir(parents=True)
        native.write_json(output / "experiment.json", dict(identity=identity, started_at=native.now(),
                          provenance=inspections[CONDITIONS[0]["name"]]["provenance"]))
    print(json.dumps(dict(event="diagnostic_prepared", cases_per_condition=40, conditions=list(CONDITIONS),
        thinking="enabled", same_input_verified=True, reference_successes=identity["reference_successes_in_selected_cases"])), flush=True)
    if args.prepare_only:
        return 0
    for condition in CONDITIONS:
        print(json.dumps(dict(event="acceptance_start", condition=condition["name"])), flush=True)
        probe = output / ("probe_" + condition["name"])
        execute(condition, probe, [CANARY], inspections[condition["name"]], args.workers)
        _, audit = audit_condition(probe, condition["model"])
        native.write_json(probe / "condition-audit.json", audit)
    result_rows, reports = {}, {}
    for condition in CONDITIONS:
        print(json.dumps(dict(event="condition_start", condition=condition["name"], n=40)), flush=True)
        path = output / condition["name"]
        execute(condition, path, identity["cases"], inspections[condition["name"]], args.workers)
        result_rows[condition["name"]], audit = audit_condition(path, condition["model"])
        reports[condition["name"]] = dict(summary=json.loads((path / "summary.json").read_text()), request_audit=audit)
    paired = []
    for case in identity["cases"]:
        key = native.case_key(case)
        paired.append(dict(case_key=key, outcomes={name: dict(attack_success=rows[key]["attack_success"], utility=rows[key]["utility"])
                                                  for name, rows in result_rows.items()}))
    native.write_json(output / "comparison.json", dict(conditions=reports, paired_outcomes=paired,
        cases_per_condition=40, complete=True, interpretation="Diagnostic sample; not a full benchmark score."))
    (output / "batch.done").write_text(native.now() + "\n")
    print(json.dumps(dict(event="diagnostic_complete", output=str(output))), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
