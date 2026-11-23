# AgentDojo Replay Classification Implementation Plan

**Goal:** Add reproducible trajectory-classification F1/Recall/FPR without inventing per-action safety labels or online prevention outcomes.

**Architecture:** A separate CPU-only post-processing module reads frozen source labels and verified replay records. Main protocol discriminates official source-successful attacks from benign-task trajectories; source-unsuccessful attacks remain outside this label definition. Complete methods share exactly the same valid case IDs. Running methods are reported as pending, never silently used to shrink the common cohort.

**Tech Stack:** Python standard library, unittest, existing JSONL summaries and SHA256 verification; no model/API invocation.

## Post-hoc protocol frozen before this calculation, not preregistered

- Positive: `stage=under_attack` and official source `attack_success=1` (459 planned).
- Negative: `stage=benign` (97 planned). This is a task-cohort label, not a claim that every benign-condition action has been independently certified safe.
- Excluded: 490 source-unsuccessful attacked trajectories; attack failure does not prove a safe trajectory.
- Prediction1: first saved BLOCK/HOLD anywhere in the recorded replay. An intervention after harm still counts as trajectory detection, not prevention.
- Main table: intersection of successful cases across complete, verified methods; report all error/missing counts and common-ID exclusions. Retain separate method-specific valid-cohort metrics for traceability.
- Report TP/FP/TN/FN, F1/Recall/FPR, balanced accuracy, prevalence, and an always-intervene reference. Latency is recomputed on the selected common cohort, not mixed with the full1046 mean.
- These are project-defined source-outcome/cohort classification metrics, not author-native AgentDojo action-safety scores or guarded ASR/Utility. Do not compare absolute F1 directly with ATBench safety-label F1.

## Tasks

1. Add label/error/common-cohort tests in `tests/test_replay_classification.py`; verify the missing module fails before implementation.
2. Add `agentguard/replay_classification.py`: immutable run loading, source/outcome checks, verified artifact hashes, same-ID metrics, JSON/Markdown output.
3. Run targeted tests locally/server; execute CPU post-processing on the four finished methods and list SafePred as pending if incomplete.
4. Update the latest benchmark report, clarify the existing Pro row as zero-shot classification with a borrowed author template, and preserve its score. A plain-prompt baseline would be a separate experiment, not a result-selected replacement.
5. Back up source/docs to GitHub; raw replay results and keys stay excluded. Give a rerunnable summary command for SafePred completion.
