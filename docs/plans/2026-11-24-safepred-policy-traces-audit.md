# SafePred policy repair and TRACES audit Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Repair SafePred's policy preparation/acceptance without changing its author inference core; establish whether TRACES's high SafetyDrift score reflects leakage or an easier evaluation protocol.

**Architecture:** Add a versioned, explicitly project-adapted normative policy specification, run the original author's complete extraction workflow, and fail policy admission if coverage/provenance checks fail. Reuse existing verified evaluation and native replay code after admission. Add a CPU-only dataset/provenance audit for TRACES, including training-only shortcut baselines and scenario/prefix overlap. Preserve all historical scores, checkpoints, split IDs and user drafts.

**Tech Stack:** Python stdlib/PyYAML, pinned SafePred/TRACES author checkouts, existing local Qwen3-8B inference transport, bash/tmux. One GPU process owns a model's mutable capture/history/RNG; independent dataset auditing is CPU-only.

## Design choices

1. Recommended: repair policy source and admission first, keep original Qwen3-8B, temperature0.3, seed42, max4000, penalty0.8/root0.7 and seven-action history. This isolates policy effects.
2. Replacing the backbone simultaneously would confound policy and model effects; leave it for a separate experiment.
3. Lowering thresholds cannot fix the present binary 0/0.8 score chain; do not tune on test outcomes or force agreement with a paper score.

Normative source text is our documented operationalization of public benchmark/task safety requirements, not an author-provided policy preset. No test trajectories, gold risk states, expected-safe paths, lookup probabilities or observed error examples may enter policy extraction. Lexical coverage is a static guard, not proof of semantic equivalence; include paired synthetic behavior checks before formal evaluation. These fixtures are policy contracts, not benchmark cases or a tuning set.

## Task 1: Audit SafetyDrift/TRACES before changing any split

Files: create `agentguard/traces_audit.py`, `tests/test_traces_audit.py`.

1. Add tests for training-only category/scenario baselines, cross-split prefix overlap and disjointness; ensure heldout labels never affect baseline fitting.
2. Implement CPU audit of the fixed manifest/data hashes, label counts, full-input duplicates, shared early prefixes and scenario overlap. Report metadata-only baselines as diagnostic shortcuts, not deployable guards.
3. On server, verify actual Stage-A train/val/test tables and checkpoint hashes against saved manifest; inspect upstream normalization/split use.
4. If no direct leakage is found, retain 96% with its within-scenario scope and offer a separately versioned scenario-disjoint diagnostic split. Do not overwrite the original author72 or guess the unpublished DreamGuard cleaned split.

## Task 2: Repair SafePred policy preparation

Files: create `policies/specs/safepred-v2/{safetydrift,agentdojo}.json`, `agentguard/safepred_policy_v2.py`, `tests/test_safepred_policy_v2.py`.

1. Specify clear normative clauses and provenance; distinguish them from descriptions of dataset labeling. Include safety and permitted behavior so legitimate reads/commands/payments are not blanket-blocked.
2. Call original `process_policy_input` through existing `extract_policies`, with the same Qwen3-8B transport. Never patch generated rules silently.
3. Add admission checks for required normative coverage in policy descriptions, goal-alignment P000, source/spec/extractor/policy hashes and model/source identities. Reject the old SafetyDrift labeling-only file.
4. Run paired synthetic safe/unsafe contracts through the same native review path. Fail before formal evaluation if these fail; retain outputs for review. No automatic prompt retries to chase expected scores.
5. Freeze admitted artifacts in a new output directory, never modify the historical frozen policy files.

## Task 3: Prepare sequential retest commands

Files: create `scripts/run-safepred-policy-v2.sh`; reuse `agentguard.safepred_author_eval`, `agentguard.native_replay` and their verification tools.

1. Stage explicit preparation/admission, SafetyDrift72, then AgentDojo Pro1046; keep ATBench unchanged because its policy source did not exhibit the same defect.
2. Require the verified original Pro bundle and a new output root. Record config/code/split/source hashes, progress and independent exit codes. A failed admission prevents formal tests.
3. Supply user-launchable private-tmux commands, GPU preflight and result-check commands. Do not start new formal GPU experiments unless the user explicitly requests it.

## Task 4: Verify and deliver

1. Run new CPU tests locally and on the server; run targeted native SafePred and data-boundary regressions using real author modules with simulated transport. Validate launch shell syntax and data audit without generating model predictions.
2. Sync only intended files under `/data1/yaoziao/agentguard`, compare LF-normalized hashes, back up source and documentation to the user's GitHub. Preserve the six existing user drafts byte-for-byte.
3. Report TRACES audit evidence and remaining limits, distinguish repaired tooling from not-yet-run scores, and give concrete start commands.

## Audit-driven refinement before formal experiments

CPU audit confirms original72 category-majority F1=92.31%, scenario-majority F1=97.30% (fit on train only), versus TRACES96%. All37 test scenarios appear in training;35/72 test trajectories share early prefixes. No heldout feature rows occur in actual training tables, and saved checkpoint/causal decisions verify.

The separate seed42 scenario split has207/72/73 trajectories across23/8/8 scenarios, but its category-majority diagnostic is already100% F1. Therefore do not automatically retrain it or pretend scene isolation alone repairs the benchmark; retain it as an optional, transparently confounded diagnostic. Prioritize reporting shortcuts and mixed-label performance; future stronger data need matched safe/unsafe task pairs. Do not change seeds based on these findings.

Short real-Qwen policy extraction plus synthetic-only contracts is code integration acceptance, not a formal72/1046 benchmark run. Keep its artifacts isolated; user launches formal tests after admission.
