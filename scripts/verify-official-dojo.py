"""Offline acceptance check of a completed official AgentDojo batch; no LLM calls."""

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import socket
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agentguard.native_agentdojo import verify_install


def text(content):
    if isinstance(content, str):
        return content
    return "\n".join(block.get("text", block.get("content", "")) for block in content or [])


def executed_tools(messages, calls):
    """Recover executed calls across the author's possible query restarts.

    Native TraceLogger retains the last query. Earlier executed calls remain
    in saved API request histories. A tool result proves execution; a pending
    assistant tool call alone does not. Deduplicate repeated history snapshots.
    """
    result, seen = [], set()
    query, previous_length = 0, 0

    def add(call, error):
        identifier = (query, call.get("id"), call["function"], json.dumps(call["args"], sort_keys=True))
        if identifier not in seen:
            seen.add(identifier)
            result.append((call, error))

    for event in calls:
        history = event["request"]["messages"]
        if len(history) < previous_length:
            query += 1
        previous_length = len(history)
        pending = {}
        for message in history:
            if message["role"] == "assistant":
                for call in message.get("tool_calls") or []:
                    pending[call["id"]] = dict(id=call["id"], function=call["function"]["name"],
                                                args=json.loads(call["function"]["arguments"]))
            elif message["role"] == "tool":
                add(pending[message["tool_call_id"]], isinstance(message["content"], str))
    for message in messages:
        if message["role"] == "tool":
            add(message["tool_call"], bool(message.get("error")))
    return result, query


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path)
    args = parser.parse_args()
    root = args.run.resolve()
    provenance = verify_install()
    from agentdojo.agent_pipeline.agent_pipeline import load_system_message
    from agentdojo.agent_pipeline.llms.openai_llm import _function_to_openai
    from agentdojo.attacks.attack_registry import load_attack
    from agentdojo.base_tasks import BaseUserTask
    from agentdojo.functions_runtime import FunctionCall, FunctionsRuntime
    from agentdojo.models import MODEL_NAMES
    from agentdojo.task_suite.load_suites import get_suite
    from types import SimpleNamespace

    def no_network(*args, **kwargs):
        raise RuntimeError("Network disabled in offline verifier")
    socket.socket.connect = no_network
    socket.create_connection = no_network
    plan = json.loads((root / "plan.json").read_text())
    summary = json.loads((root / "summary.json").read_text())
    meta = json.loads((root / "run_metadata.json").read_text())
    config = plan["configuration"]
    assert summary["complete"] and (root / "batch.done").exists(), "Batch is incomplete"
    assert hashlib.sha256((Path(__file__).resolve().parents[1] / "agentguard/native_agentdojo.py").read_bytes()).hexdigest() == meta["runner_sha256"]
    cases = {row["case_key"]: row for row in map(json.loads, (root / "cases.jsonl").read_text().splitlines())}
    assert len(cases) == len(plan["cases"])
    MODEL_NAMES[config["model"]] = config["attack_model_name"]
    counters, visible, models = Counter(), Counter(), Counter()
    api_calls, reset_cases = 0, []
    expected_system = load_system_message(None)
    for spec in plan["cases"]:
        key = "--".join((spec["stage"], spec["suite"], spec["task_id"], spec["injection_id"] or "none"))
        row = cases[key]
        assert row["status"] == "ok", key
        suite = get_suite("v1.2.2", spec["suite"])
        task = (suite.get_injection_task_by_id(spec["task_id"]) if spec["stage"] == "capability"
                else suite.get_user_task_by_id(spec["task_id"]))
        prompt = task.PROMPT if isinstance(task, BaseUserTask) else task.GOAL
        messages = row["messages"]
        calls = [json.loads(line) for line in Path(row["api_log"]).read_text().splitlines()]
        assert text(messages[0]["content"]) == expected_system, key
        assert text(next(message["content"] for message in messages if message["role"] == "user")) == prompt, key
        if spec["stage"] == "under_attack":
            attacker = load_attack("important_instructions", suite, SimpleNamespace(name=config["model"]))
            expected = attacker.attack(task, suite.get_injection_task_by_id(spec["injection_id"]))
            assert expected == row["injections"], key
        else:
            assert row["injections"] == {}, key
        environment = suite.load_and_inject_default_environment(row["injections"])
        if isinstance(task, BaseUserTask):
            environment = task.init_environment(environment)
        before = environment.model_copy(deep=True)
        runtime, stack = FunctionsRuntime(suite.tools), []
        for message in messages:
            if message["role"] == "assistant":
                stack.extend(FunctionCall.model_validate(call) for call in message.get("tool_calls") or [])
        executed, resets = executed_tools(messages, calls)
        if resets:
            reset_cases.append(dict(case_key=key, query_restarts=resets))
        for value, expected_error in executed:
            call = FunctionCall.model_validate(value)
            _, error = runtime.run_function(environment, call.function, call.args)
            assert bool(error) == expected_error, (key, call.function)
        output = messages[-1]["content"] or []
        assert int(bool(suite._check_task_result(task, output, before, environment, stack))) == row["utility"], key
        if spec["stage"] == "under_attack":
            injection = suite.get_injection_task_by_id(spec["injection_id"])
            assert int(bool(suite._check_task_result(injection, output, before, environment, stack))) == row["attack_success"], key
        assert len(calls) == row["api_calls"], key
        seen = False
        for call in calls:
            request = call["request"]
            assert request["model"] == config["model"] and request["temperature"] == config["temperature"], key
            assert text(request["messages"][0]["content"]) == expected_system, key
            assert request["messages"][0]["role"] == config["system_role"], key
            assert request["tools"] == [_function_to_openai(tool) for tool in suite.tools], key
            seen |= any("<INFORMATION>" in text(message.get("content")) for message in request["messages"] if message["role"] == "tool")
            if "response" in call:
                models[call["response"].get("model", "unknown")] += 1
            api_calls += 1
        counters[spec["stage"]] += 1
        visible[spec["stage"]] += int(seen)
    for stage, size in counters.items():
        values = [row for row in cases.values() if row["stage"] == stage]
        expected = summary["stages"][stage]
        assert expected["completed_cases"] == size
        assert expected["utility_successes"] == sum(row["utility"] for row in values)
        if stage == "under_attack":
            assert expected["attack_successes"] == sum(row["attack_success"] for row in values)
    report = dict(verified_cases=sum(counters.values()), stages=dict(counters), checker_mismatches=0,
                  verified_api_calls=api_calls, response_models=dict(models), injection_seen_in_api_requests=dict(visible),
                  author_query_restart_cases=reset_cases,
                  official_provenance=provenance, network_disabled=True)
    (root / "verification.json").write_text(json.dumps(report, indent=2) + "\n")
    (root / "verified.done").write_text("ok\n")
    print(json.dumps(report))


if __name__ == "__main__":
    main()
