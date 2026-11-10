import argparse
import os
import platform
import subprocess
import sys
from datetime import datetime, timezone
from hashlib import sha256
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from .atbench import read_rows, read_split, run_atbench
from .guard import AGENTDOG_08B, json_text, load_agentdog, write_record
from .safepred import DEFAULT_SAFEPRED_MODEL, POLICY_VERSION, load_safepred


def positive(text: str) -> int:
    value = int(text)
    if value < 1:
        raise argparse.ArgumentTypeError("expected a positive integer")
    return value


def git_revision(root: Path) -> str | None:
    try:
        head = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"], capture_output=True, text=True)
    except FileNotFoundError:
        return None
    return head.stdout.strip() if head.returncode == 0 else None


def runtime_versions() -> dict[str, str]:
    versions = {"python": platform.python_version()}
    for package in ("torch", "transformers", "openai", "agentdojo"):
        try:
            versions[package] = version(package)
        except PackageNotFoundError:
            continue
    return versions


def main() -> int:
    parser = argparse.ArgumentParser(prog="python -m agentguard")
    commands = parser.add_subparsers(dest="benchmark", required=True)
    atbench = commands.add_parser("atbench", help="classify ATBench trajectories")
    atbench.add_argument("--data", type=Path, required=True)
    atbench.add_argument("--config", choices=("ATBench", "ATBench500"), default="ATBench")
    atbench.add_argument("--method", choices=("agentdog", "safepred", "traces"), default="agentdog")
    atbench.add_argument("--split-manifest", type=Path)
    atbench.add_argument("--split", choices=("train", "calibration", "heldout"), default="heldout")
    atbench.add_argument("--replay", action="store_true", help="review recorded proposals in order")
    atbench.add_argument("--case-id", action="append", default=[])
    atbench.add_argument("--limit", type=positive)
    dojo = commands.add_parser("agentdojo", help="evaluate the task agent with a runtime guard")
    dojo.add_argument("--ipiguard-root", type=Path, required=True)
    dojo.add_argument("--method", choices=("agentdog", "safepred", "traces", "none", "ipiguard"), default="agentdog")
    dojo.add_argument("--agent-model", default="deepseek-v4-pro")
    dojo.add_argument("--mode", choices=("benign", "under_attack"), default="under_attack")
    dojo.add_argument("--suite", action="append", choices=("workspace", "slack", "travel", "banking"))
    dojo.add_argument("--attack", default="important_instructions")
    dojo.add_argument("--user-task-id", type=int)
    dojo.add_argument("--injection-task-id", type=int)
    scope = dojo.add_mutually_exclusive_group()
    scope.add_argument("--limit", type=positive)
    scope.add_argument("--all-cases", action="store_true")
    for command in (atbench, dojo):
        command.add_argument("--guard-model")
        command.add_argument("--revision")
        command.add_argument("--device", default="cuda")
        command.add_argument("--max-new-tokens", type=positive)
        command.add_argument("--env-file", type=Path)
        command.add_argument("--traces-run", type=Path)
        command.add_argument("--traces-upstream", type=Path, default=Path("vendor/TRACES"))
        command.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.method == "agentdog":
        args.guard_model = args.guard_model or AGENTDOG_08B
        args.max_new_tokens = args.max_new_tokens or 512
    if args.method == "safepred":
        args.guard_model = args.guard_model or DEFAULT_SAFEPRED_MODEL
        args.max_new_tokens = args.max_new_tokens or 2048
    if args.method == "traces" and not args.traces_run:
        parser.error("--traces-run is required for TRACES")

    metadata = {
        "record_type": "run_metadata",
        "benchmark": args.benchmark,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "agentguard_commit": git_revision(Path(__file__).resolve().parents[1]),
        "runtime_versions": runtime_versions(),
        "configuration": {k: str(v) if isinstance(v, Path) else v for k, v in vars(args).items()},
    }
    if args.output.exists():
        parser.error(f"Output already exists: {args.output}")
    if args.benchmark == "atbench":
        replay = args.replay or args.method == "safepred"
        case_ids = args.case_id
        split = None
        if args.split_manifest:
            if args.case_id or args.limit or args.config != "ATBench":
                parser.error("--split-manifest requires ATBench and excludes --case-id and --limit")
            split = read_split(args.split_manifest)
            case_ids = list(map(str, split["splits"][args.split]))
        data_sha, cases = read_rows(args.data, args.config, case_ids, args.limit)
        if split and data_sha != split["source_sha256"]:
            parser.error("ATBench source SHA-256 does not match the split manifest")
        metadata.update(dataset_sha256=data_sha, split=args.split if split else "test",
                        split_id=split["id"] if split else None,
                        protocol="pre_action_replay" if replay else "full_trajectory")
        env_file = args.env_file
    else:
        root = args.ipiguard_root.resolve()
        if not (root / "run" / "eval_support.py").is_file():
            parser.error("--ipiguard-root must refer to the instrumented IPIGuard checkout")
        env_file = args.env_file or root / ".env"
        if args.mode == "benign" and args.injection_task_id is not None:
            parser.error("--injection-task-id requires --mode under_attack")
        args.suite = args.suite or ["workspace"]
        args.limit = None if args.all_cases else args.limit or 1
        sys.path[:0] = [str(root), str(root / "agentdojo" / "src")]
        from .agentdojo import run_agentdojo

        metadata.update(
            benchmark_version="v1.2.2",
            protocol="pre_action" if args.method in ("agentdog", "safepred", "traces") else args.method,
            ipiguard_commit=git_revision(root),
            excluded_user_tasks=["workspace:25"],
            effective_suites=args.suite,
            case_limit_per_suite=args.limit,
        )
    if args.benchmark == "agentdojo" or args.method == "safepred":
        from dotenv import load_dotenv

        load_dotenv(env_file)
        if not os.getenv("OPENAI_API_KEY") or not os.getenv("OPENAI_BASE_URL"):
            parser.error("Configure OPENAI_API_KEY and OPENAI_BASE_URL or pass --env-file")
    guard, revision = None, None
    if args.method == "agentdog":
        guard, revision = load_agentdog(args.guard_model, args.revision, args.device, args.max_new_tokens)
        metadata["guard_dtype"] = "float32" if args.device == "cpu" else "bfloat16"
    elif args.method == "safepred":
        guard = load_safepred(args.guard_model, args.max_new_tokens)
        metadata.update(guard_variant="SafePred-prompt", policy_version=POLICY_VERSION, guard_thinking=False)
    elif args.method == "traces":
        from .traces import load_traces

        guard, trace_run = load_traces(args.traces_run, args.traces_upstream, args.device)
        if args.benchmark == "atbench" and (
            data_sha != trace_run["dataset_sha256"] or args.split_manifest and (
                trace_run["smoke"] or sha256(args.split_manifest.read_bytes()).hexdigest() != trace_run["split_sha256"]
            )
        ):
            parser.error("TRACES checkpoint does not match this ATBench source and split")
        revision = trace_run["observer_revision"]
        metadata["traces"] = trace_run
    metadata["guard_revision"] = revision
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8", newline="\n") as output:
        write_record(output, metadata)
        if args.benchmark == "atbench":
            summary = run_atbench(guard, cases, output, replay=replay)
        else:
            summary = run_agentdojo(args, guard, output)
    print(json_text(summary))
    return int(bool(summary["error_cases"]))


if __name__ == "__main__":
    raise SystemExit(main())
