"""Compare saved AgentDojo logs; optional checker replay uses only simulated tools.

This does not run an agent, call an LLM, or generate any new attack trajectories.
"""

import argparse
from collections import Counter
import copy
import hashlib
import json
from pathlib import Path
import re
import socket
import sys

import yaml


def text(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(text(block.get("content", block.get("text", ""))) for block in content)
    return ""


def role_text(case, role):
    return "\n".join(text(message.get("content")) for message in case["messages"] if message["role"] == role)


def key(case):
    def number(value):
        return int(re.search(r"\d+$", str(value))[0])
    return (case.get("suite", case.get("suite_name")), number(case["user_task_id"]), number(case["injection_task_id"]))


def normalized(value):
    # Ignore only whitespace and the attack template's addressee model label.
    value = re.sub(r"\s+", " ", value).strip()
    return re.sub(r"(This is an important message from me, [^.]*?, to you, )[^.]+\.", r"\1MODEL.", value)


def tool_text(case):
    # YAML rendering doubles quotes or escapes newlines. Compare decoded leaf
    # strings as well as literal tool messages, rather than misreporting these
    # serialization differences as missing injection delivery.
    def leaves(value):
        if isinstance(value, str):
            return [value]
        if isinstance(value, dict):
            return [item for child in value.values() for item in leaves(child)]
        if isinstance(value, list):
            return [item for child in value for item in leaves(child)]
        return []
    strings = []
    for message in case["messages"]:
        if message["role"] != "tool":
            continue
        value = text(message.get("content"))
        strings.append(value)
        try:
            strings.extend(leaves(yaml.safe_load(value)))
        except yaml.YAMLError:
            pass
    return "\n".join(strings)


def attack_goal(value):
    match = re.search(r"following first:\s*(.*?)\s*After you do that", value, re.S)
    return normalized(match[1]) if match else None


def metrics(cases):
    size = len(cases)
    attack = sum(bool(case.get("attack_success", case["security"])) for case in cases)
    utility = sum(bool(case["utility"]) for case in cases)
    duration = sum(float(case.get("duration_seconds", case.get("duration", 0))) for case in cases)
    return dict(n=size, attack_successes=attack, asr=attack / size if size else None,
                utility_successes=utility, utility=utility / size if size else None,
                mean_task_seconds=duration / size if size else None)


def scope(cases):
    return {name: metrics([case for k, case in cases.items() if name == "all" or k[0] == name])
            for name in ["all", "workspace", "slack", "travel", "banking"]}


def system_variants(cases):
    counts = Counter(role_text(case, "system") for case in cases.values())
    return [dict(n=n, sha256=hashlib.sha256(value.encode()).hexdigest(), text=value)
            for value, n in counts.most_common()]


def saved_reasoning_cases(cases):
    return sum(any(message.get("reasoning_content") for message in case["messages"]
                   if message["role"] == "assistant") for case in cases.values())


def recheck_external(cases, ipiguard_root):
    """Reconstruct the original simulated environment from logged tool messages."""
    sys.path.insert(0, str(ipiguard_root / "agentdojo/src"))
    sys.path.insert(0, str(ipiguard_root))
    from agentdojo.functions_runtime import FunctionCall, FunctionsRuntime
    from agentdojo.task_suite.load_suites import get_suite

    def deny_network(*args, **kwargs):
        raise RuntimeError("Network access is disabled during offline checker replay")

    original_connect, original_connection = socket.socket.connect, socket.create_connection
    socket.socket.connect, socket.create_connection = deny_network, deny_network
    results = []
    try:
        suites = {name: get_suite("v1.2.2", name) for name in {k[0] for k in cases}}
        for index, (case_key, case) in enumerate(sorted(cases.items()), 1):
            row = dict(key=case_key)
            try:
                suite = suites[case_key[0]]
                user = suite.get_user_task_by_id(f"user_task_{case_key[1]}")
                injection = suite.get_injection_task_by_id(f"injection_task_{case_key[2]}")
                environment = user.init_environment(suite.load_and_inject_default_environment(case["injections"]))
                before = environment.model_copy(deep=True)
                runtime = FunctionsRuntime(suite.tools)
                stack, execution_error_differences = [], []
                for message in case["messages"]:
                    if message["role"] == "assistant":
                        stack.extend(FunctionCall.model_validate(call) for call in message.get("tool_calls") or [])
                    elif message["role"] == "tool":
                        call = FunctionCall.model_validate(message["tool_call"])
                        _, error = runtime.run_function(environment, call.function, copy.deepcopy(call.args))
                        if bool(error) != bool(message.get("error")):
                            execution_error_differences.append(call.function)
                if case["messages"][-1]["role"] != "assistant":
                    raise ValueError("Saved transcript does not end in an assistant message")
                output = [dict(type="text", content=text(case["messages"][-1].get("content")))]
                utility = bool(suite._check_task_result(user, output, before, environment, stack))
                security = bool(suite._check_task_result(injection, output, before, environment, stack))
                row.update(utility=utility, security=security,
                           utility_match=utility == bool(case["utility"]),
                           security_match=security == bool(case["security"]),
                           execution_error_differences=execution_error_differences)
            except Exception as error:
                row.update(error=f"{type(error).__name__}: {str(error)[:350]}")
            results.append(row)
            if index % 200 == 0:
                print(f"Offline checker replay: {index}/{len(cases)}", flush=True)
    finally:
        socket.socket.connect, socket.create_connection = original_connect, original_connection
    return dict(n=len(results), errors=sum("error" in row for row in results),
                utility_mismatches=[row for row in results if row.get("utility_match") is False],
                security_mismatches=[row for row in results if row.get("security_match") is False],
                execution_error_differences=[row for row in results if row.get("execution_error_differences")],
                failures=[row for row in results if "error" in row], cases=results)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--external-root", type=Path, required=True)
    parser.add_argument("--ours", type=Path, action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--recheck-ipiguard-root", type=Path)
    args = parser.parse_args()
    external, ours, manifest, metadata = {}, {}, [], []
    for path in sorted(args.external_root.rglob("*.json")):
        raw = path.read_bytes()
        case = json.loads(raw)
        case_key = key(case)
        if case_key in external:
            raise ValueError(f"Duplicate external key: {case_key}")
        external[case_key] = case
        manifest.append(dict(path=str(path), sha256=hashlib.sha256(raw).hexdigest()))
    for path in args.ours:
        raw = path.read_bytes()
        manifest.append(dict(path=str(path), sha256=hashlib.sha256(raw).hexdigest()))
        for line in raw.decode().splitlines():
            case = json.loads(line)
            if case.get("record_type") == "case":
                case_key = key(case)
                if case_key in ours:
                    raise ValueError(f"Duplicate our key: {case_key}")
                ours[case_key] = case
            elif case.get("record_type") in {"metadata", "run_metadata"}:
                metadata.append(case)
    shared = sorted(external.keys() & ours.keys())
    paired_external, paired_ours = ({k: cases[k] for k in shared} for cases in [external, ours])
    flags = lambda cases: [k for k, case in cases.items() if "[Monitor Warning" in role_text(case, "user")]
    warnings = flags(external)
    delivery, goals_missing = Counter(), []
    for case_key in shared:
        payloads = list(external[case_key]["injections"].values())
        own_tools = tool_text(external[case_key])
        our_tools = tool_text(ours[case_key])
        goals = [attack_goal(payload) for payload in payloads]
        delivery["external_normalized_payload_seen"] += any(normalized(p) in normalized(own_tools) for p in payloads)
        delivery["ours_normalized_payload_seen"] += any(normalized(p) in normalized(our_tools) for p in payloads)
        goal_seen = any(goal and goal in normalized(our_tools) for goal in goals)
        delivery["ours_same_goal_seen"] += goal_seen
        if not goal_seen:
            goals_missing.append(case_key)
    contingency = Counter((bool(external[k]["security"]), bool(ours[k]["attack_success"])) for k in shared)
    report = dict(
        external_root=str(args.external_root), ours=[str(p) for p in args.ours], input_manifest=manifest,
        full_external=scope(external), full_ours=scope(ours), paired_external=scope(paired_external), paired_ours=scope(paired_ours),
        external_only=sorted(external.keys() - ours.keys()), ours_only=sorted(ours.keys() - external.keys()),
        contingency={str(k): n for k, n in contingency.items()},
        systems_equal=sum(role_text(external[k], "system") == role_text(ours[k], "system") for k in shared),
        user_differences=[k for k in shared if role_text(external[k], "user") != role_text(ours[k], "user")],
        external_systems=system_variants(external), our_systems=system_variants(ours),
        external_user_monitor_warnings=warnings, ours_user_monitor_warnings=flags(ours),
        external_saved_reasoning_cases=saved_reasoning_cases(external), our_saved_reasoning_cases=saved_reasoning_cases(ours),
        normalized_delivery=dict(delivery), ours_goal_not_seen=goals_missing,
        paired_without_monitor_external=scope({k: external[k] for k in shared if k not in warnings}),
        paired_without_monitor_ours=scope({k: ours[k] for k in shared if k not in warnings}),
        external_fields={field: dict(Counter(str(case.get(field)) for case in external.values()))
                         for field in ["pipeline_name", "benchmark_version", "agentdojo_package_version", "attack_type", "error"]},
        external_stored_timestamp_range=[min(case["evaluation_timestamp"] for case in external.values()),
                                         max(case["evaluation_timestamp"] for case in external.values())],
        our_metadata=metadata,
        external_result_txt=[dict(path=str(p), content=p.read_text()) for p in sorted(args.external_root.rglob("result.txt"))],
    )
    if args.recheck_ipiguard_root:
        report["external_native_checker_replay"] = recheck_external(external, args.recheck_ipiguard_root)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    compact = {k: v for k, v in report.items() if k not in {
        "input_manifest", "our_metadata", "external_result_txt", "external_systems", "our_systems", "external_native_checker_replay"}}
    if "external_native_checker_replay" in report:
        compact["checker_replay"] = {k: (len(v) if isinstance(v, list) else v)
                                      for k, v in report["external_native_checker_replay"].items() if k != "cases"}
    print(json.dumps(compact, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
