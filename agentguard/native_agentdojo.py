"""Run the unchanged official AgentDojo package in an isolated environment.

Invoke this module directly; the historical ``python -m agentguard agentdojo``
command deliberately continues to identify the older IPIGuard-based protocol.
"""

import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
import copy
from datetime import datetime, timezone
import hashlib
from importlib import metadata
import json
import multiprocessing
import os
from pathlib import Path
import subprocess
import sys
import time
from types import SimpleNamespace
from urllib.parse import urlsplit, urlunsplit


PROJECT = Path(__file__).resolve().parents[1]
MANIFEST = PROJECT / "configs/agentdojo-official-v0.1.35.json"
SUITES = ("workspace", "slack", "travel", "banking")
STAGES = ("benign", "capability", "under_attack")
PROTOCOL = "agentdojo-official-0.1.35-v1.2.2-author-lock-none-v1"
_WORKER = None


def now():
    return datetime.now(timezone.utc).isoformat()


def plain(value):
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    raise TypeError(f"Cannot serialize {type(value).__name__}")


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, default=plain).encode()).hexdigest()


def write_json(path, value):
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=plain) + "\n", encoding="utf-8")
    temporary.replace(path)


def append_json(path, value):
    with path.open("a", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(value, ensure_ascii=False, default=plain) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def verify_files(site_root, manifest):
    for relative, expected in manifest["files"].items():
        path = site_root / relative
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise RuntimeError(f"Official AgentDojo file differs from pinned wheel: {relative}")


def verify_install():
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    distribution = metadata.distribution("agentdojo")
    if distribution.version != manifest["version"]:
        raise RuntimeError("Use the dedicated official AgentDojo 0.1.35 environment")
    for package, expected in manifest["critical_dependency_versions"].items():
        actual = metadata.version(package)
        if actual != expected:
            raise RuntimeError(f"Dependency differs from author uv.lock: {package}={actual}, expected {expected}")
    if hashlib.sha256((PROJECT / "requirements-native-dojo-author.txt").read_bytes()).hexdigest() != manifest["author_requirements_sha256"]:
        raise RuntimeError("Author dependency export differs from its frozen hash")
    site_root = Path(distribution.locate_file("")).resolve()
    verify_files(site_root, manifest)
    import agentdojo

    root = site_root / "agentdojo"
    if Path(agentdojo.__file__).resolve().parent != root:
        raise RuntimeError(f"Unexpected AgentDojo import location: {agentdojo.__file__}")
    for name, module in tuple(sys.modules.items()):
        if name.startswith("agentdojo.") and getattr(module, "__file__", None):
            if not Path(module.__file__).resolve().is_relative_to(root):
                raise RuntimeError(f"Mixed AgentDojo source trees: {name}")
    return dict(distribution_version=distribution.version, package_root=str(root),
                upstream_git_commit=manifest.get("upstream_git_commit"),
                author_uv_lock_sha256=manifest["author_uv_lock_sha256"],
                author_requirements_sha256=manifest["author_requirements_sha256"],
                pinned_wheel_sha256=manifest["wheel_sha256"], verified_files=len(manifest["files"]),
                manifest_sha256=hashlib.sha256(MANIFEST.read_bytes()).hexdigest())


def author_runtime(model, display_name):
    from agentdojo.agent_pipeline.agent_pipeline import AgentPipeline, PipelineConfig
    from agentdojo.agent_pipeline.llms import openai_llm
    from agentdojo.attacks.attack_registry import load_attack
    from agentdojo import benchmark
    from agentdojo.models import MODEL_NAMES
    from agentdojo.task_suite.load_suites import get_suite

    # Add the missing provider model label without editing any author source.
    MODEL_NAMES[model] = display_name
    return SimpleNamespace(AgentPipeline=AgentPipeline, PipelineConfig=PipelineConfig,
                           llm=openai_llm, load_attack=load_attack, benchmark=benchmark, get_suite=get_suite)


def case_key(case):
    return "--".join((case["stage"], case["suite"], case["task_id"], case.get("injection_id") or "none"))


def number(task_id):
    return int(task_id.rsplit("_", 1)[1])


def inventory(args):
    provenance = verify_install()
    runtime = author_runtime(args.model, args.attack_model_name)
    cases, scopes, schemas, candidate_errors = [], {}, {}, []
    excluded = set(getattr(args, "exclude_user_task", []))
    available = set()
    dummy = SimpleNamespace(name=args.model)
    for name in args.suite:
        suite = runtime.get_suite("v1.2.2", name)
        all_users = sorted(suite.user_tasks, key=number)
        available.update(f"{name}:{number(uid)}" for uid in all_users)
        users = [uid for uid in all_users if f"{name}:{number(uid)}" not in excluded]
        injections = sorted(suite.injection_tasks, key=number)
        scopes[name] = dict(user_tasks=len(users), source_user_tasks=len(all_users),
                           injection_tasks=len(injections), attack_cases=len(users) * len(injections))
        schemas[name] = [runtime.llm._function_to_openai(tool) for tool in suite.tools]
        attacker = runtime.load_attack("important_instructions", suite, dummy)
        if args.check_candidates:
            for uid in users:
                try:
                    attacker.get_injection_candidates(suite.get_user_task_by_id(uid))
                except Exception as error:
                    candidate_errors.append(dict(suite=name, task_id=uid, error=f"{type(error).__name__}: {error}"))
        groups = {
            "benign": [dict(suite=name, stage="benign", task_id=uid, injection_id=None) for uid in users],
            "capability": [dict(suite=name, stage="capability", task_id=iid, injection_id=None) for iid in injections],
            "under_attack": [dict(suite=name, stage="under_attack", task_id=uid, injection_id=iid)
                             for uid in users for iid in injections],
        }
        for stage in args.stage:
            cases.extend(groups[stage][:args.limit_per_suite])
    if excluded - available:
        raise ValueError(f"Excluded tasks not found in selected suites: {sorted(excluded - available)}")
    from agentdojo.agent_pipeline.agent_pipeline import load_system_message

    system = load_system_message(None)
    return dict(provenance=provenance, scope=scopes, cases=cases, candidate_errors=candidate_errors,
                excluded_user_tasks=sorted(excluded),
                system_prompt=system, system_prompt_sha256=hashlib.sha256(system.encode()).hexdigest(),
                tool_schemas=schemas, tool_schema_sha256={name: digest(schema) for name, schema in schemas.items()})


class RecordingCompletions:
    """Instrument author OpenAILLM requests, retaining the original parser/loop."""

    def __init__(self, sdk, path, config):
        self.sdk, self.path, self.config = sdk, path, config
        self.chat = SimpleNamespace(completions=self)
        self.calls = []
        self.reasoning = {}

    def create(self, **kwargs):
        from openai import NOT_GIVEN

        payload = copy.deepcopy({key: value for key, value in kwargs.items() if value is not NOT_GIVEN})
        if self.config["temperature"] is None:
            payload.pop("temperature", None)
        else:
            payload["temperature"] = self.config["temperature"]
        if self.config["max_tokens"] is not None:
            payload["max_tokens"] = self.config["max_tokens"]
        if self.config["thinking"] != "provider":
            payload["extra_body"] = {"enable_thinking": self.config["thinking"] == "enabled"}
        for message in payload["messages"]:
            if message["role"] == "developer":
                message["role"] = self.config["system_role"]
            if message["role"] == "assistant":
                identifiers = [call["id"] for call in message.get("tool_calls") or []]
                reasoning = next((self.reasoning[item] for item in identifiers if item in self.reasoning), None)
                if reasoning is not None:
                    message["reasoning_content"] = reasoning
        event = dict(index=len(self.calls), started_at=now(), request=payload)
        started = time.perf_counter()
        try:
            response = self.sdk.chat.completions.create(**payload)
            event["response"] = response.model_dump(mode="json")
            for choice in event["response"].get("choices", []):
                message = choice["message"]
                if message.get("reasoning_content") is not None:
                    for call in message.get("tool_calls") or []:
                        self.reasoning[call["id"]] = message["reasoning_content"]
            return response
        except Exception as error:
            # Credentials never belong in these records. SDK body messages are
            # omitted here; raw provider error codes/status suffice for retries.
            event["error"] = dict(type=type(error).__name__, status_code=getattr(error, "status_code", None),
                                  code=getattr(error, "code", None))
            raise
        finally:
            event["latency_seconds"] = time.perf_counter() - started
            self.calls.append(event)
            append_json(self.path, event)  # Persist even if the author tool-argument parser fails next.


def init_worker(config):
    global _WORKER
    verify_install()
    from dotenv import load_dotenv
    from openai import OpenAI

    load_dotenv(config["env_file"], override=False)
    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"], base_url=os.environ["OPENAI_BASE_URL"],
                    timeout=config["timeout"], max_retries=2)
    _WORKER = (config, author_runtime(config["model"], config["attack_model_name"]), client)


def usage(calls):
    result = dict(input_tokens=0, output_tokens=0, reasoning_tokens=0)
    for call in calls:
        tokens = call.get("response", {}).get("usage") or {}
        result["input_tokens"] += tokens.get("prompt_tokens", 0) or 0
        result["output_tokens"] += tokens.get("completion_tokens", 0) or 0
        result["reasoning_tokens"] += (tokens.get("completion_tokens_details") or {}).get("reasoning_tokens", 0) or 0
    return result


def run_attempt(case, attempt, config, runtime, sdk):
    from agentdojo.logging import OutputLogger

    started = time.perf_counter()
    directory = Path(config["output"]) / "attempts" / case_key(case) / str(attempt)
    directory.mkdir(parents=True, exist_ok=False)
    native_root = directory / "native"
    transport = RecordingCompletions(sdk, directory / "api.jsonl", config)
    llm = runtime.llm.OpenAILLM(transport, config["model"], temperature=config["temperature"])
    llm.name = config["model"]
    pipeline = runtime.AgentPipeline.from_config(runtime.PipelineConfig(
        llm=llm, defense=None, model_id=None, system_message_name=None, system_message=None))
    suite = runtime.get_suite("v1.2.2", case["suite"])
    record = dict(record_type="case", case_key=case_key(case), suite=case["suite"], stage=case["stage"],
                  mode=case["stage"], method="none", protocol=PROTOCOL, attempt=attempt,
                  user_task_id=number(case["task_id"]) if case["stage"] != "capability" else None,
                  capability_task_id=case["task_id"] if case["stage"] == "capability" else None,
                  injection_task_id=number(case["injection_id"]) if case["injection_id"] else None,
                  status="error", utility=None, attack_success=None, security=None, guard_events=[],
                  native_root=str(native_root), api_log=str(directory / "api.jsonl"), started_at=now())
    task_name = case["task_id"]
    attack_name = "important_instructions" if case["stage"] == "under_attack" else "none"
    native_path = native_root / config["model"].replace("/", "_") / suite.name / task_name / attack_name / ((case["injection_id"] or "none") + ".json")
    try:
        with OutputLogger(str(native_root)):
            if case["stage"] == "under_attack":
                task = suite.get_user_task_by_id(task_name)
                attacker = runtime.load_attack("important_instructions", suite, pipeline)
                values, securities = runtime.benchmark.run_task_with_injection_tasks(
                    suite, pipeline, task, attacker, native_root, True, [case["injection_id"]], "v1.2.2")
                utility, security = next(iter(values.values())), next(iter(securities.values()))
            else:
                task = (suite.get_user_task_by_id(task_name) if case["stage"] == "benign"
                        else suite.get_injection_task_by_id(task_name))
                utility, security = runtime.benchmark.run_task_without_injection_tasks(
                    suite, pipeline, task, native_root, True, "v1.2.2")
        record.update(status="ok", utility=int(bool(utility)), security=bool(security),
                      attack_success=int(bool(security)) if case["stage"] == "under_attack" else None)
    except Exception as error:
        record.update(error_type=type(error).__name__, error_status=getattr(error, "status_code", None))
    if native_path.exists():
        native = json.loads(native_path.read_text())
        record.update(messages=native.get("messages", []), injections=native.get("injections", {}),
                      native_log=str(native_path), native_error=native.get("error"))
        if native.get("error"):
            # Preserve author-assigned utility/security above, but flag the run
            # as invalid instead of silently reporting API failure as an attack.
            record["status"] = "author_recorded_error"
    else:
        record.update(messages=[], injections={})
    record.update(usage(transport.calls))
    record.update(duration_seconds=time.perf_counter() - started, api_calls=len(transport.calls),
                  api_latency_seconds=sum(call["latency_seconds"] for call in transport.calls),
                  response_models=sorted({call["response"].get("model", "unknown") for call in transport.calls if "response" in call}))
    write_json(directory / "case.json", record)
    return record


def run_case(case):
    config, runtime, client = _WORKER
    path = Path(config["output"]) / "attempts" / case_key(case)
    start = max([int(p.name) for p in path.iterdir() if p.is_dir() and p.name.isdigit()] or [0]) + 1 if path.exists() else 1
    attempts = []
    for attempt in range(start, start + config["case_attempts"]):
        result = run_attempt(case, attempt, config, runtime, client)
        attempts.append(result)
        if result["status"] == "ok" or result.get("error_status") in (401, 403, 404):
            break
    return attempts


def summarize(planned, records, attempts):
    by_stage = {}
    for stage in STAGES:
        wanted = [case for case in planned if case["stage"] == stage]
        values = [records[case_key(case)] for case in wanted if case_key(case) in records]
        valid = [row for row in values if row["status"] == "ok"]
        attacks = sum(row["attack_success"] or 0 for row in valid) if stage == "under_attack" else None
        by_stage[stage] = dict(planned_cases=len(wanted), recorded_cases=len(values), completed_cases=len(valid),
                               error_cases=len(values) - len(valid), remaining_cases=len(wanted) - len(values),
                               utility_successes=sum(row["utility"] for row in valid),
                               utility=sum(row["utility"] for row in valid) / len(valid) if valid else None,
                               attack_successes=attacks, asr=attacks / len(valid) if valid and attacks is not None else None,
                               author_security_sum=sum(bool(row.get("security")) for row in values) if stage == "under_attack" else None)
    valid = [row for row in records.values() if row["status"] == "ok"]
    return dict(record_type="overall_summary", protocol=PROTOCOL, updated_at=now(), stages=by_stage,
                total_cases=len(planned), completed_cases=len(valid), error_cases=len(records) - len(valid),
                remaining_cases=len(planned) - len(records), attempts=len(attempts),
                input_tokens=sum(row["input_tokens"] for row in attempts),
                output_tokens=sum(row["output_tokens"] for row in attempts),
                mean_case_seconds=sum(row["duration_seconds"] for row in valid) / len(valid) if valid else None,
                f1=None, recall=None, fpr=None, guard_latency_seconds=None,
                classification_metric_note="No runtime guard or independent action-safety labels; ASR and Utility are the benchmark metrics.",
                complete=len(valid) == len(planned))


def read_records(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()] if path.exists() else []


def protocol_config(args, inspected):
    return dict(protocol=PROTOCOL, model=args.model, attack="important_instructions", attack_model_name=args.attack_model_name,
                temperature=args.temperature, thinking=args.thinking, max_tokens=args.max_tokens, system_role=args.system_role,
                author_loop_max_iters=15, author_task_output_attempts=3, author_sdk_call_attempts=3, sdk_max_retries=2,
                timeout=args.timeout, case_attempts=args.case_attempts, workers=args.workers,
                excluded_user_tasks=sorted(getattr(args, "exclude_user_task", [])),
                runner_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                dependency_versions_sha256=digest({dist.metadata["Name"]: dist.version for dist in metadata.distributions()}),
                source_manifest=inspected["provenance"]["manifest_sha256"],
                system_prompt_sha256=inspected["system_prompt_sha256"], tool_schema_sha256=inspected["tool_schema_sha256"])


def run(args, inspected):
    from dotenv import load_dotenv

    load_dotenv(args.env_file, override=False)
    if not os.getenv("OPENAI_API_KEY") or not os.getenv("OPENAI_BASE_URL"):
        raise RuntimeError("Configure AgentGuard's OPENAI_API_KEY and OPENAI_BASE_URL before running")
    if inspected["candidate_errors"]:
        raise RuntimeError(f"Official injection candidate preflight failed: {inspected['candidate_errors']}")
    url = urlsplit(os.environ["OPENAI_BASE_URL"])
    safe_url = urlunsplit((url.scheme, url.netloc.rsplit("@", 1)[-1], url.path, "", ""))
    configuration = protocol_config(args, inspected)
    configuration["base_url"] = safe_url
    plan = dict(configuration=configuration, cases=inspected["cases"])
    plan_hash = digest(plan)
    output = args.output.resolve()
    if output.exists():
        if not args.resume or not (output / "plan.json").is_file():
            raise RuntimeError("Output exists; use --resume with the identical protocol to retain all prior attempts")
        previous = json.loads((output / "plan.json").read_text())
        if digest(previous) != plan_hash:
            raise RuntimeError("Resume refused: protocol or selected cases changed")
    else:
        output.mkdir(parents=True)
        write_json(output / "plan.json", plan)
        write_json(output / "inventory.json", inspected)
        write_json(output / "run_metadata.json", dict(record_type="run_metadata", started_at=now(),
                   plan_sha256=plan_hash, configuration=configuration, env_file=str(args.env_file),
                   provider_defaults_unknown=[key for key, omitted in [("temperature", args.temperature is None),
                                              ("thinking", args.thinking == "provider"),
                                              ("max_tokens", args.max_tokens is None)] if omitted],
                   provenance=inspected["provenance"], python=sys.version, executable=sys.executable,
                   dependencies={dist.metadata["Name"]: dist.version for dist in metadata.distributions()},
                   runner_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                   compatibility_changes=["developer role mapped to configured gateway role; prompt unchanged",
                       "temperature omitted" if args.temperature is None else "explicit temperature preserves zero",
                       "added model display-name mapping",
                       "echo returned reasoning_content for continued tool calls", "case-level error retries logged separately"]))
    records = {row["case_key"]: row for row in read_records(output / "cases.jsonl")}
    attempts = read_records(output / "attempts.jsonl")
    config = {**configuration, "output": str(output), "env_file": str(args.env_file)}
    for stage in STAGES:
        pending = [case for case in inspected["cases"] if case["stage"] == stage and
                   (case_key(case) not in records or records[case_key(case)]["status"] != "ok")]
        if not pending:
            continue
        print(json.dumps(dict(event="stage_start", stage=stage, pending=len(pending), workers=args.workers)), flush=True)
        with ProcessPoolExecutor(max_workers=args.workers, mp_context=multiprocessing.get_context("spawn"),
                                 initializer=init_worker, initargs=(config,)) as executor:
            futures = {executor.submit(run_case, case): case for case in pending}
            for future in as_completed(futures):
                results = future.result()
                for result in results:
                    append_json(output / "attempts.jsonl", result)
                    attempts.append(result)
                record = results[-1]
                append_json(output / "cases.jsonl", record)
                records[record["case_key"]] = record
                summary = summarize(inspected["cases"], records, attempts)
                write_json(output / "summary.json", summary)
                print(json.dumps(dict(event="case_complete", case_key=record["case_key"], status=record["status"],
                                      progress=summary["stages"][stage])), flush=True)
                if record.get("error_status") in (401, 403, 404):
                    for pending_future in futures:
                        pending_future.cancel()
                    raise RuntimeError("Stopped batch after an authentication/permission/model-route failure; see saved API error codes")
    summary = summarize(inspected["cases"], records, attempts)
    write_json(output / "summary.json", summary)
    if summary["complete"]:
        (output / "batch.done").write_text(now() + "\n")
    print(json.dumps(summary, ensure_ascii=False), flush=True)
    return 0 if summary["complete"] else 1


def positive(value):
    result = int(value)
    if result < 1:
        raise argparse.ArgumentTypeError("must be positive")
    return result


def temperature(value):
    if value == "provider":
        return None
    result = float(value)
    if not 0 <= result <= 2:
        raise argparse.ArgumentTypeError("temperature must be provider or a number from 0 to 2")
    return result


def excluded_task(value):
    try:
        suite, identifier = value.split(":")
        identifier = int(identifier)
        if suite not in SUITES or identifier < 0:
            raise ValueError
    except ValueError as error:
        raise argparse.ArgumentTypeError("expected SUITE:ID, e.g. slack:7") from error
    return f"{suite}:{identifier}"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("inspect", "run"))
    parser.add_argument("--model", default="deepseek-v4-flash-0731")
    parser.add_argument("--attack-model-name", default="DeepSeek")
    parser.add_argument("--suite", action="append", choices=SUITES)
    parser.add_argument("--stage", action="append", choices=STAGES)
    parser.add_argument("--exclude-user-task", action="append", type=excluded_task, default=[])
    parser.add_argument("--limit-per-suite", type=positive)
    parser.add_argument("--workers", type=positive, default=4)
    parser.add_argument("--temperature", type=temperature, default=0.0,
                        help="explicit value, or provider to omit temperature entirely")
    parser.add_argument("--thinking", choices=("provider", "enabled", "disabled"), default="provider")
    parser.add_argument("--max-tokens", type=positive)
    parser.add_argument("--system-role", choices=("system", "developer"), default="system")
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument("--case-attempts", type=positive, default=2)
    parser.add_argument("--env-file", type=Path, default=PROJECT / ".env")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--skip-candidate-check", dest="check_candidates", action="store_false")
    args = parser.parse_args()
    args.suite = args.suite or list(SUITES)
    args.stage = args.stage or list(STAGES)
    if len(set(args.suite)) != len(args.suite) or len(set(args.stage)) != len(args.stage):
        parser.error("Duplicate suites or stages")
    inspected = inventory(args)
    if args.command == "inspect":
        print(json.dumps({key: value for key, value in inspected.items() if key not in ("cases", "tool_schemas", "system_prompt")}, indent=2))
        if args.output:
            if args.output.exists():
                parser.error("Inspection output exists")
            args.output.parent.mkdir(parents=True, exist_ok=True)
            write_json(args.output, inspected)
        return int(bool(inspected["candidate_errors"]))
    if not args.output:
        parser.error("run requires --output")
    return run(args, inspected)


if __name__ == "__main__":
    raise SystemExit(main())
