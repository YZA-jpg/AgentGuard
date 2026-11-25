# SafePred observed-state and parallel evaluation Implementation Plan

**Goal:** Repair confirmed loss of previously visible tool results and GUI/tool semantics mismatch, and allow isolated trajectory-level parallelism without altering the active v2 run.

**Architecture:** New state-projection wrapper around unchanged author core and frozen v2 policies. Four explicit arms (legacy, memory, tools, memory-tools) make effects separable. A process-per-worker evaluator owns its own model/guard/RNG/log, with stable per-case seeds, saved shard plans, resumable complete records and a CPU saved-response verifier. Shared test labels never enter prompts or selection.

**Tech Stack:** Python, subprocess workers, original Qwen3-8B transport, pinned SafePred author modules, CPU unit/native-core tests. All server files under data1; source/docs/frozen configuration in Git.

## Evidence and scope

- Active v2 remains running; no changes to `safepred_author.py`, original runner, v2 policy files/specs or admission code.
- On all36 SafetyDrift v2 FN trajectories, first-hazard prompts omit earlier visible observations (103 observations total). This confirms information loss, not its numerical causal contribution.
- Saved forecasts treat direct send/upload tools as GUI composition rather than completed side effects. New adapter metadata states function-call semantics without adding scenario-specific hazard rules.
- Original paper input includes current state, recent interactions, candidate, intent, policies and plan. Fixed tool recordings have no GUI or reliable actor plan; do not fabricate a plan or access future results.
- Default new evaluation is development calibration, not another test-driven repair. Use the same frozen policy/model/decoding settings. History7, max4000, temperature0.3; binary0/.8 scoring and .7 decision threshold unchanged.

## Task 1: Causal observed-state projection

Files: new `agentguard/safepred_observed_state.py`, `tests/test_safepred_observed_state.py`.

- Tests demonstrate that neutral-file confidential/public histories collapse to one legacy prompt but differ with memory; current candidate result/gold never enters.
- Keep at most7 prior tool observations including latest. The author still sees its original seven-response history. Put older visible observations in a clearly tagged state bundle, with candidate unexecuted.
- Add a separate direct-tool metadata flag. Preserve user task, tools, candidate and original action order.
- Budget old observation entries as whole units before native fitting; record drops and native truncation. Reuse AuthorSafePred.review/parser/scorer/root without upstream edits.

## Task 2: Independent-process parallel runner and verification

Files: new `agentguard/safepred_parallel.py`, `tests/test_safepred_parallel.py`, `scripts/run-safepred-development.sh`.

- Freeze dataset/split/policy/admission/code hashes and job IDs before model execution. Default calibration12 (6 per label selected by fixed seed/hash), four arms,2 workers.
- Accept explicit GPU list (two processes can share an80GB GPU only if aggregate free-memory admission passes). Each worker has a separate model/capture/RNG; no threaded shared AuthorSafePred instance.
- Seed each trajectory by stable dataset/case ID, independent of worker scheduling; same seed across arms. This is a new reproducibility protocol, not identical to old single global RNG stream.
- Flush each completed case to its shard; resume only an identical plan, rejecting partial/duplicate/unknown case records. Global merge fails if coverage missing, preserves errors and reports throughput separately from per-review latency.
- CPU verification reconstructs causal reviews/projection/budget and replays saved responses through original author code, checking scores, decisions, coverage and summary. No model generation in verification.

## Task 3: Verify and deliver

- Run pure CPU tests locally, native-core tests on the server, parser/launcher smoke and hash parity checks.
- If a genuinely available GPU supports a short synthetic paired integration, run it isolated; do not launch formal72/1046 automatically.
- Document facts versus hypotheses, paper/model/online-loop differences, concurrency semantics and a user-launchable development ablation command. Do not promise improved benchmark F1 until validated.
- Back up code/docs to GitHub, preserve all user drafts and the in-flight v2 results.
