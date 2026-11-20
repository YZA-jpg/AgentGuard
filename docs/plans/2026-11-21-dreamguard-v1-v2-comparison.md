# DreamGuard v1 / v2 paired run

User explicitly authorized starting both versions and comparing them on 2026-11-21.

1. Freeze tracked package snapshots from v1 commit `526257e` and v2 commit `629584c`. Do not edit their model/training code or mix package imports. Use the installed server environment and official Qwen snapshot.
2. Validate v1's historical frozen-feature cache against exact code, data, encoder, split and text-source hashes. Reuse those immutable features to save repeated Qwen encoding; train fresh world/risk weights in a new directory. Preserve historical train/calibration behavior (281/69).
3. On the same A100 GPU, run v1 and then v2 sequentially. V2 keeps 221/57/72 and evaluates SafetyDrift 72 plus ATBench 1000. Source feature extraction batch remains 8. Neither version uses target labels for training/calibration.
4. After both finish, reload the two new checkpoints and their own calibrated thresholds. Evaluate the exact same ATBench 200 IDs with a common causal text-to-decision timer, preserving each version's pooling and action serialization. No feature-text cache hits in this paired latency measurement.
5. Automatically write per-case paired JSONL, aggregate F1/Recall/FPR/latency tables, native-vs-paired differences and status/error files. Also display v2 full-1000 and SafetyDrift72 results separately; do not call v1's SafetyDrift calibration data an independent test.
6. Validate controller/reporting with CPU tests and frozen-source imports. Deploy under data1, back up source to GitHub, start in private tmux socket, and verify startup without promising unobserved results.

Interpretation: this measures the aggregate effect of the v1/v2 protocol changes, not a one-factor causal ablation. A single training seed cannot establish variance. GPU3 shares the server with a pre-existing vLLM process; record resource snapshots and treat latency as measurements under the observed shared-server load.
