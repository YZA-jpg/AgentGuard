# Official AgentDojo Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use executing-plans to implement this plan task-by-task. The user has authorized implementation and the subsequent Flash test in this chat; continue through verification and launch without another approval checkpoint.

**Goal:** Replace IPIGuard-dependent AgentDojo evaluation with a separately invoked, verifiable official benchmark workflow, then retest DeepSeek-v4-Flash-0731.

**Architecture:** A clean server venv installs the official AgentDojo 0.1.35 distribution. A new `agentguard.native_agentdojo` entry point delegates prompts, tools, execution loops, injection candidate selection and scoring to the unchanged package. Only the OpenAI-compatible transport and experiment logging are adapted. Independent worker processes preserve per-case environments and author logger isolation.

**Tech Stack:** Python >=3.10, official AgentDojo 0.1.35 / benchmark v1.2.2, OpenAI-compatible SDK, multiprocessing, JSONL, unittest, tmux. Server artifacts and caches stay on `/data1`.

**Final dependency decision:** Use the author's original `uv.lock`, exported with `--frozen --no-dev --no-emit-project` and hash-checked, plus the verified official wheel. The first modern-dependency comparison batch completed and is preserved; formal author-lock execution uses `.venv-agentdojo-author`. Nine offline checks and the twelve-case actual API acceptance passed. The author-lock full batch was started at 20:15 BJT. The user then requested that this batch continue, and that future tests be supplied as launch commands with reasonable concurrency rather than automatically started or monitored; this preference is recorded in `AGENTS.md`.

---

## Design and scope

The selected approach is an isolated official distribution. Patching IPIGuard would retain unexamined fork behavior; writing another simulator would make fidelity harder to establish. Existing legacy code and result files remain available under their documented historical protocol. Do not touch the user's dirty AgentDojo/replay drafts.

Flash uses the configured API and model `deepseek-v4-flash-0731`. Run ordinary tasks without injections, author injection-task-as-user capability checks, then all user/injection combinations for `important_instructions`, with four independent API worker processes. Derive IDs from the official suite and explicitly report any original data problems; do not carry over the fork's Workspace-25 exclusion. Save exact API requests/responses, native trace JSON, source/prompt/schema hashes, requested versus unknown provider defaults, errors/retries, ASR, Utility, token usage and timings. F1/Recall/FPR are unavailable without separate action labels and must remain null.

Compatibility changes must be explicit: system-role mapping if required by the gateway, an added Flash-to-DeepSeek display-name mapping for the author attack, optional reasoning-content echo required by the provider, and explicit temperature 0 instead of the upstream adapter's falsy-zero omission. Thinking and token cap default to provider behavior, as the author code does, and must be recorded as omitted rather than guessed effective values. Preserve native loop limit and native checker behavior. Author-mapped API errors must be separately flagged and never silently treated as successful valid cases.

## Task 1: Pin and verify official assets

- Create `configs/agentdojo-official-v0.1.35.json` from the official wheel, with wheel SHA256 and package file hashes.
- Create the dedicated `.venv-agentdojo-official` and retain a dependency freeze. Do not inherit system site packages or import `IPIGuard` / `run.eval_support`.
- Verify all pinned files, package import location, original system prompt and tool schemas before any API call.
- Inspect full official case enumeration and injection eligibility offline. Record differences from the previous 96/935 coverage.

## Task 2: Implement transport instrumentation and native runner

- Create `agentguard/native_agentdojo.py` with `inspect` and `run` commands.
- Wrap the SDK client used by official `OpenAILLM`; keep author benchmark and pipeline implementations unchanged.
- Save raw response data including reasoning, usage, response model, finish reason and malformed tool arguments before the author parser runs. Log errors with no credentials.
- Delegate single cases to author `run_task_without_injection_tasks` and `run_task_with_injection_tasks`, retaining native trace files.
- Write each attempt separately; aggregate final valid outcomes without discarding errors or retries. Protect resumption with a frozen protocol/case manifest.

## Task 3: Meaningful offline verification

- Create `tests/test_native_agentdojo.py`.
- Verify source tampering is rejected, benign/precheck/security semantics are separate, zero temperature is retained, reasoning can be echoed, malformed responses are retained, and resume cannot change the protocol.
- Compare deterministic scripted trajectories through the official pipeline with and without the recording wrapper; tool calls and task outcomes must agree.
- Run the relevant new tests against the clean official installation. Preserve unrelated local drafts.

## Task 4: Server smoke and formal Flash run

- Add `scripts/run-official-flash.sh` and a concise runbook with paths, configurations and deviations.
- Sync only new workflow files; copy existing API settings into AgentGuard's own ignored `.env` without displaying values.
- Run one case per suite per stage as a smoke check; inspect actual requests, prompt/schema hashes, trajectories and errors before launching the full batch.
- Use the private tmux socket under AgentGuard's `/data1/.../cache/tmux`, four API workers and sequential stages. Save durable progress and exit markers. Confirm completed case records exist after launch.

## Task 5: Documentation and backup

- Document final official counts, verification results, run directory, monitor commands and remaining differences from the paper.
- Commit only new workflow assets and documentation; fast-forward the main checkout while preserving the user's drafts, then push the authorized GitHub backup.
- Report whether the formal run is complete or still running using observed counts. Do not describe smoke scores as full results.
