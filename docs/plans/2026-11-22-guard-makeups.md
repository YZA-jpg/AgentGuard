# Guard Makeup Runs Implementation Plan

> **For Claude:** Execute this plan task by task in the current isolated worktree. The user has explicitly authorized starting these makeup runs.

**Goal:** Retry the single failed AgentDoG Pro replay case, evaluate ShieldAgent-THU on the original SafetyDrift test72, and summarize current ATBench/AgentDojo results.

**Architecture:** Preserve every existing result. Prepare an error-only native replay bundle; run the existing frozen adapter; merge only matching failed IDs into a new verified view. Add a separate SafetyDrift ShieldAgent entry point that reuses the original author scorer/checkpoint and the existing causal dataset loader, without modifying the active SafePred batch.

**Tech Stack:** Python, unittest, official Transformers checkpoints, existing native replay verification, SSH and tmux; all remote artifacts on data1.

---

### Task 1: Error-only native replay preparation and merge

- Add `agentguard/replay_makeup.py` and integrity tests in `tests/test_guard_makeups.py`.
- Validate source bundle hash, case identity, old summary and frozen guard configuration.
- Select only failed cases; keep all original successful records unchanged in the merged output.
- Run `agentguard.native_replay` with the same 1024-token AgentDoG configuration; reject changed-configuration merges.
- Independently verify every merged visible input and saved decision. A repeated parsing error remains an error; do not fabricate a verdict.

### Task 2: ShieldAgent on SafetyDrift

- Add `agentguard/shieldagent_safetydrift.py` and tests for candidate serialization, gold exclusion and verification tampering.
- Reuse official THU weights/scorer/generation config, native32k, FP16/SDPA and FFN chunks1024.
- Use `safetydrift_data.reviews`: task, preceding executed history, current proposed action; never its result or risk labels.
- First run two calibration smoke cases, then untouched heldout72. First BLOCK/HOLD marks a dangerous trajectory, matching existing SafetyDrift evaluations.
- Save raw responses, input hashes, truncation counts and independent metric/decision verification. Recovery FPR stays null.

### Task 3: Run and record

- Add `scripts/run-guard-makeups.py` for two independent GPU lanes, with per-stage logs, exit statuses and a batch lock.
- Run targeted CPU tests locally and on the server; sync only new files and check hashes.
- Recheck free GPUs, then explicitly launch authorized makeup jobs with AgentDoG on GPU4 and ShieldAgent on GPU5.
- If a deterministic AgentDoG retry still omits its judgment, retain the failed 1024-token main protocol. Any longer-output diagnostic must be separately labeled and must not replace the main result.
- Produce a concise Markdown report with paired ATBench200, separate full1000/different-split results, native Pro/Flash baselines and Pro fixed-trace intervention metrics. Record source paths and current SafePred progress.
- Back up source and report to GitHub; raw traces and credentials remain excluded.

### Authorized follow-through: paired TRACES and separate budget diagnosis

- `scripts/run-traces-paired-k8.py` reuses the unchanged author training/evaluation code. It preserves the original heldout200/calibration200, excludes only no-tool-action908 from train (599 remain), freezes K8/threshold0.3, and independently verifies train/test separation, IDs, labels and metrics. Fresh feature extraction runs on GPU6, with no heldout tuning.
- `scripts/diagnose-agentdog-replay.py` changes only the output cap to2048 for the one failed case, stores a separate result and verifies its inputs. It cannot be merged into the1024 main protocol. Both1024 and2048 attempts omitted the required judgment; retain the error transparently.
