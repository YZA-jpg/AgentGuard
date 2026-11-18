# SafetyDrift Baselines Implementation Plan

**Goal:** Evaluate Flash direct classification, AgentDoG 1.5 4B, SafePred-prompt and TRACES on the same 72 author-test trajectories, with saved causal reviews and timing.

**Architecture:** Adapt the pinned public SafetyDrift traces to the existing `Review`/`Guard` interfaces. Retain the original 72 test IDs. Remove duplicate test content from the original training pool before making a stratified training/calibration split. Reuse the pinned TRACES author's Stage-A/Stage-B implementations if no released author checkpoint is available.

**Tech Stack:** Python, PyTorch, Transformers, OpenAI-compatible DashScope API, upstream TRACES commit `87579ab60ce6b13f38f7d1f531b6a906656f2748`.

The user confirmed the original test set and requested author weights first, otherwise local training. Existing SafetyDrift trajectories are sufficient: Flash is a direct classification baseline, not a newly collected unguarded-agent trajectory run. ShieldAgent remains pending its implementation assets; DreamGuard is excluded.

## Task 1: Freeze data and causal inputs

- Create `agentguard/safetydrift_data.py` and `tests/test_safetydrift.py`.
- Test that current tool results, later observations, gold risk states, tool risk profiles and expected safe paths are absent from model inputs.
- Use the author's first `safety_state_after.risk_level == 4` boundary. One public trace has a conflicting `is_violation_step` flag; follow the loader and record the discrepancy.
- Keep all 72 original test IDs, including 38 unsafe and 34 safe. Deduplicate only the training pool, prioritizing held-out test content, then split the remaining pool 80/20 by category and label with seed 42.
- Save case IDs, source hashes, content hashes, discarded duplicate IDs and split counts in `splits/safetydrift-public-v1.json`.

Frozen inventory: 222 training (117 unsafe), 57 calibration (31 unsafe), 72 test (38 unsafe). Six duplicate development records were removed; the 72 original test IDs are unchanged. The release has no explicit recovery field and no observed decreases in the annotated risk level, so a recovery FPR is not inferred from those states.

The original protocol splits trajectories rather than scenarios: training covers 39 scenarios, calibration 32, and test 37. All 37 test scenarios occur in training. Results therefore measure held-out trajectories under the source protocol, not generalization to unseen scenarios. None of the recorded observations is marked truncated. Tool-call thoughts can be null; candidate tool names and arguments are still present.

Calibration-only inspection also confirmed a semantic/annotation mismatch: in the dependency-update trajectory, a package-registry GET after reading CI data reaches the source risk-level-4 boundary, while AgentDoG judges the action safe. The adapter retains the public labels. This reflects the release's tool/state labeling convention and must not be silently fixed using model judgments.

## Task 2: Implement common evaluation

- Create `agentguard/safetydrift_eval.py`.
- Use identical task, tool schema, historical observations and candidate action boundaries for all four groups. Strip post-action results from candidate calls.
- Flash: `deepseek-v4-flash-0731`, temperature 0, thinking disabled, 1024 tokens. AgentDoG: official 4B revision `3193b58d0c8924f5b5a79eb99cd31918e327024c`, greedy, 1024 tokens. Both use the author's coarse prompt with an explicitly documented proposed-action wrapper.
- SafePred-prompt: preserve the existing adaptation, `deepseek-v4-pro`, temperature 0.3, thinking disabled, 2048 tokens and policy version `agentguard-safepred-v1`.
- Save per-review verdicts, latency, visible-input hashes, first-intervention positions, per-case labels and aggregate F1/Recall/FPR/PHIR/MAS. Measure calls from input to verdict; cached feature timings must not replace online call timings.
- API concurrency 4 across independent trajectories; GPU models use one process. Exceptions remain errors and are excluded from classification counts with explicit coverage.

## Task 3: Train TRACES using author code

- Create `agentguard/traces_safetydrift.py` without editing the upstream checkout.
- Freeze official Qwen3-4B observer revision `1cfa9a7208912126459214e8b04321603b3df60c`, layer 32. Map every SafetyDrift decision (tool or text response) to an action-end representation. Do not read test features in the training loop.
- Reuse author's Stage A and Stage B, with paper K=8, released 30/30 epochs, batch 32, LR 5e-4, seed 42. Record this new dataset adapter separately from author-published SafetyDrift results.
- Author-asset audit: pinned GitHub tree contains no `.pt`, `.pth`, `.ckpt` or `.safetensors` files; GitHub releases list is empty. Targeted public search found no matching author SafetyDrift checkpoint; a server Hugging Face model API lookup timed out. This records what was checked, rather than claiming that no private or unindexed checkpoint exists.
- Select the checkpoint and decision threshold using calibration data only. Save both trained checkpoints, configuration, hashes and calibration metrics.

## Task 4: Verify, launch, and collect

- Run `python -m unittest discover -s tests -v`; run the upstream training integration smoke on a separate tiny training/calibration directory.
- Add `scripts/run-safetydrift-baselines.sh`. Run 2-case smoke for all four methods, then 72-case formal groups. Select a free GPU immediately before launch; use one GPU serially for local models while independent API groups may overlap.
- Follow the server job to completion, retry only failed cases if needed, and preserve original logs.
- Update `docs/baseline-runs.md`, copy result summaries and checkpoints locally, and back up code/configuration to the user's GitHub repository. Do not claim the results reproduce the DreamGuard paper's SafetyDrift table.

## Completion and audit · 2026-11-19

Canonical run: `results/safetydrift-baselines-20261118_191442`. All four formal groups completed 72/72 with zero errors and zero failed audit attempts. Model parameters and results are recorded in `docs/baseline-runs.md`; all 1,766 review inputs were independently reconstructed and compared against the causal adapter, and confusion matrices/timing metrics were recomputed from the saved verdicts.

TRACES used the actual 222 training trajectories (1,832 decisions) and 57 calibration trajectories (484 decisions) in the author's saved tables. No test features were present in training. Full action-end message-sequence hashes have zero overlap across train/calibration/test. Checkpoint hashes were verified. Calibration chose threshold 0.8 with F1 98.36%; the fixed test result is F1 96.00%, Recall 94.74%, FPR 2.94%. Test labels were used only for scoring. The 37 test scenarios all occur in training under the original trajectory split, which limits interpretation as cross-scenario transfer.
