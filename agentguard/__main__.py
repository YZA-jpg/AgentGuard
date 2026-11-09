import argparse
import os
import platform
import subprocess
import sys
from datetime import datetime, timezone
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from .atbench import read_rows, run_atbench
from .guard import AGENTDOG_08B, json_text, load_agentdog, write_record


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
    atbench = commands.add_parser("atbench", help="classify completed ATBench trajectories")
    atbench.add_argument("--data", type=Path, required=True)
    atbench.add_argument("--config", choices=("ATBench", "ATBench500"), default="ATBench")
    atbench.add_argument("--case-id", action="append", default=[])
    atbench.add_argument("--limit", type=positive)
    dojo = commands.add_parser("agentdojo", help="evaluate the task agent with a runtime guard")
    dojo.add_argument("--ipiguard-root", type=Path, required=True)
    dojo.add_argument("--method", choices=("agentdog", "none", "ipiguard"), default="agentdog")
    dojo.add_argument("--env-file", type=Path)
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
        command.add_argument("--guard-model", default=AGENTDOG_08B)
        command.add_argument("--revision")
        command.add_argument("--device", default="cuda")
        command.add_argument("--max-new-tokens", type=positive, default=512)
        command.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

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
        data_sha, cases = read_rows(args.data, args.config, args.case_id, args.limit)
        metadata.update(dataset_sha256=data_sha, split="test", protocol="full_trajectory")
        guard, revision = load_agentdog(args.guard_model, args.revision, args.device, args.max_new_tokens)
    else:
        from dotenv import load_dotenv

        root = args.ipiguard_root.resolve()
        if not (root / "run" / "eval_support.py").is_file():
            parser.error("--ipiguard-root must refer to the instrumented IPIGuard checkout")
        env_file = args.env_file or root / ".env"
        load_dotenv(env_file)
        if not os.getenv("OPENAI_API_KEY") or not os.getenv("OPENAI_BASE_URL"):
            parser.error("Configure OPENAI_API_KEY and OPENAI_BASE_URL before running AgentDojo")
        if args.mode == "benign" and args.injection_task_id is not None:
            parser.error("--injection-task-id requires --mode under_attack")
        args.suite = args.suite or ["workspace"]
        args.limit = None if args.all_cases else args.limit or 1
        sys.path[:0] = [str(root), str(root / "agentdojo" / "src")]
        from .agentdojo import run_agentdojo

        metadata.update(
            benchmark_version="v1.2.2",
            protocol="pre_action" if args.method == "agentdog" else args.method,
            ipiguard_commit=git_revision(root),
            excluded_user_tasks=["workspace:25"],
            effective_suites=args.suite,
            case_limit_per_suite=args.limit,
        )
        guard, revision = (load_agentdog(args.guard_model, args.revision, args.device, args.max_new_tokens)
                           if args.method == "agentdog" else (None, None))

    metadata["guard_revision"] = revision
    if guard is not None:
        metadata["guard_dtype"] = "float32" if args.device == "cpu" else "bfloat16"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8", newline="\n") as output:
        write_record(output, metadata)
        if args.benchmark == "atbench":
            summary = run_atbench(guard, cases, output)
        else:
            summary = run_agentdojo(args, guard, output)
    print(json_text(summary))
    return int(bool(summary["error_cases"]))


if __name__ == "__main__":
    raise SystemExit(main())
