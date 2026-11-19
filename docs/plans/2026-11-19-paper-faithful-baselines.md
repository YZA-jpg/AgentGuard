# Paper-faithful Baseline Reproduction Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Prioritize fidelity to each paper and its released implementation before interpreting scores; keep cross-dataset evaluations and historical adaptations explicitly labeled.

**Architecture:** Use author checkpoints and executable inference/training code wherever available. Keep benchmark-specific adapters minimal, freeze a versioned effective configuration and input manifest, and verify author-example behavior before launching a formal run. Original-paper protocols and common ATBench paired comparisons are separate experiments.

**Tech Stack:** Python 3.10+, pinned author Git checkouts and Hugging Face revisions, PyTorch/Transformers, existing AgentGuard adapters and JSONL records. Prepare code locally; server weights, downloads, caches and results stay under `/data1/yaoziao/agentguard`.

---

## Standing reproduction requirements

1. Prefer released author checkpoints and core code to a handwritten imitation. Read the paper's experimental configuration as well as repository defaults; a default/example configuration can be an ablation or demo.
2. Freeze model identity/revision, prompt bytes/hash, policy source/hash, input fields and causal boundary, train/cal/test IDs, truncation, decoding and decision thresholds before reading test outcomes. Select only unspecified hyperparameters using independent train/calibration data, with the choice documented.
3. Use each method's own published prompt and decision pipeline. Sharing the same input evidence does not require replacing every prompt with AgentDoG's template. A backbone substitution such as Pro must be named as a separate controlled variant, not silently substituted for the original model.
4. Native offline classification and online intervention are distinct protocols. Offline traces cannot reproduce SafePred's action regeneration and replanning loop, or establish guarded online ASR/utility.
5. Preserve author-specific evaluation scopes. For example, the AgentDoG ATBench paper uses the 1,000-trajectory benchmark, whereas TRACES trains a separate supervised model on a train/validation/test split. Do not evaluate that trained TRACES checkpoint on its training trajectories to force all methods into a full-1,000 table.
6. Keep three explicit statuses: author assets with documented benchmark adaptation; independent/partial method adaptation; not yet validated. None automatically implies numerical reproduction of an author's table. Missing original assets/split IDs/configuration must remain listed as limitations.
7. Report failed/truncated outputs and review latency according to the declared protocol. No test-label threshold tuning, test-driven seed selection or changes made solely to approach a reference score.

## Audit snapshot, 2026-11-19

| Method | Verified assets/current implementation | Outstanding differences | Result disposition |
|---|---|---|---|
| AgentDoG 1.5 4B | Official checkpoint `3193b58d0c8924f5b5a79eb99cd31918e327024c`; author coarse prompt at repository `c8d803f267a43ec0e103a651265f50f1ff4456d5`; role formatting and tool schema included | Current 73.49% F1 is only the existing paired 200. Our output budget is 1024, while the pinned getting-started example uses 512; our explicit thinking/greedy settings must also be checked against the model's effective generation config. A demo's parameters do not prove the paper's exact evaluation configuration. | Keep as author-model adapted subset evaluation, not a direct reproduction of the paper's 74.3% full-benchmark score. Complete full-1,000 author-protocol evaluation after config audit. |
| ShieldAgent-THU | Official THU model `a62f8413908bf3dbb1aea2edfbbeae54fdfd383c` and scorer `74feea8de601b3a1449a93fcf70017fe61556f73`; native scorer prompt/greedy 10-token config; 1,000 + paired-200 outputs verified | This is THU Agent-SafetyBench's model, not the same-name ICML rule-circuit method. ATBench role/call/environment adaptation, batch 1, SDPA and native-32k truncation are recorded differences. YaRN is an extension, not a native-paper setting. | Keep as official THU checkpoint transfer evaluation. Preserve native 32k main setting and separate long25 extension as user selected; do not call it an ICML ShieldAgent reproduction. |
| SafePred | Current `agentguard/safepred.py` is handwritten: five fixed policies, custom JSON prompt, Pro, no execution plan, any policy flag blocks | Official author implementation now verified at `https://github.com/YurunChen/SafePred`, pinned locally to `495890eafce02f9990e494493891c4549114a2dc`. Current code has not used its prompt, policy integration, state conversion, score parser or decision loop. Original paper evaluates WASP/OS-Harm, not ATBench. | Existing ATBench 66.21% and SafetyDrift 73.68% remain historical SafePred-prompt adaptations and are excluded from a paper-reproduction comparison. Prioritize author-core integration, then label ATBench/SafetyDrift as new-dataset adaptations. |
| TRACES K=8 | Unmodified author Stage-A/Stage-B modules `87579ab60ce6b13f38f7d1f531b6a906656f2748`; Qwen3-4B layer 32; K=8; 30/30 epochs; public README threshold 0.3; 7500-token left truncation matches native extractor | Input feature extraction, event/action conversion and saved split must still be compared to native executable pipeline; exact author's original split IDs are unavailable in the pinned release, so ours is algorithm-reconstructed. | Retain 80.54% as author-code/parameter reproduction with reconstructed split and documented adapter. Do not call it exact numerical reproduction or compare it as paired with the original 200. |
| TRACES K=32 | Historical author's code configuration with our paired 600/200/200 split and calibration threshold 0.195 | K differs from paper's K=8, and threshold/split also differ. | 81.34% remains historical paired adaptation, excluded from the paper-configuration primary comparison. |
| DreamGuard | Independent implementation and previously documented architectural/training differences | No matching author checkpoint/code/split package verified. Old checkpoint used 69 of the current SafetyDrift 72 test IDs for calibration. | Remains excluded per user instruction until implementation and independent validation are accepted. |
| Pro direct judge | Generic model with AgentDoG author template and supplied tool schema | This is our controlled generic-judge baseline; no claim that it is a paper's official DeepSeek configuration | Keep only as a clearly named auxiliary/control row; it is not evidence that SafePred's original method underperforms Pro. |

## Task 1: Correct result labels and retain evidence

**Files:** modify `docs/atbench-latest-results.md`, `docs/baseline-runs.md`, `docs/plans/2026-11-19-audit-shieldagent-atbench.md`; update ignored local `results/atbench-latest-summary-20261119.json` statuses.

1. Label already-completed executions separately from validated paper reproduction. Move no raw files and change no scores.
2. Mark SafePred-prompt and TRACES K=32 as historical adaptations; retain DreamGuard's exclusion.
3. Keep author full-benchmark results and supervised heldout results in separate scopes; never reuse a trained checkpoint's training cases as a common full-1,000 test.
4. Check the documentation diff and preserve the user's unrelated AgentDojo drafts before committing to GitHub.

## Task 2: Replace handwritten SafePred core

**Files to inspect:** `vendor/SafePred-official/{wrapper.py,models/world_model.py,models/prompts.py,agent/agent.py,config/config.yaml,config/config.py,core/conversation_history_manager.py,docs/POLICY_EXTRACTION.md}`. Future implementation should use a separately named module/config rather than relabeling old runs in place.

1. Keep the author checkout unmodified at the pinned commit. Audit its imports and interfaces before executing it.
2. Record an important paper/code-default discrepancy: at this commit, YAML uses `gpt-4o-mini`, conversation `max_length: 3`, and long-term prediction disabled. The paper's main experiment uses Qwen3-Max and describes temperature 0.3/history 7 and both prediction horizons. Do not blindly treat YAML as paper-main settings. Confirm whether history is counted as messages or interactions at the adapter boundary.
3. Reuse author prompt construction, output parsing, risk calculation and root filtering. The current released code maps any nonempty violation list to a fixed configured penalty; YAML penalty 0.8 and root threshold 0.7 make that branch effectively binary. **Nonempty-list blocking alone is therefore not an established difference or cause of our false positives.** Handwritten policies, different prompt/state/history/plan and backbone remain verified differences.
4. Source benchmark policies from author assets or benchmark specifications and apply the author's extraction/review/dedup pipeline, excluding test verdicts and post-action gold fields. Freeze the actual policy file/hash; do not reuse our five generic sentences under an official label. The repo does not supply an ATBench/SafetyDrift policy preset, so those mappings remain declared adaptations.
5. Use an original-paper world-model backbone when the exact named endpoint/checkpoint is available; verify model identity and effective settings. Keep Pro as an explicitly separate variant if tested. Do not substitute a newer model silently when the paper's snapshot is unavailable.
6. For fixed-trace evaluation, implement only the pre-action risk-evaluation path and disclose unavailable plans. For online AgentDojo, connect official regeneration/guidance/plan updates rather than merely returning a generic tool error. Frozen-trace replay is not an online-loop reproduction.
7. Before any formal run, test author prompt/parse/score behavior on fixed mocked responses, including no violations, actual violation penalty/root threshold, malformed output, disabled/enabled long-term fields, and one causal-prefix example. Compare adapter risk/verdict to the unmodified author functions on identical input. These tests establish contract equivalence, not an expected benchmark score.

## Task 3: Validate AgentDoG and TRACES against native entry points

**Files:** `agentguard/{guard.py,atbench.py,traces.py,traces_train.py}`, pinned author inference/extraction/training files, and `splits/{atbench-v1.json,atbench-traces-seed42.json}`.

1. For AgentDoG, render fixed cases using the pinned getting-started formatter and our formatter; compare role order, task text, actions, observations and tool fields, excluding labels. Record checkpoint generation config and every overridden parameter.
2. Treat a 512-token author-example control and a 1024-token robustness variant as separate if exact paper decoding settings cannot be established. Keep parse failures visible; do not regenerate only difficult test cases with a different budget and present that as a fixed-budget run.
3. For TRACES, compare identical full token sequences and selected last-action token states to the native extractor, then compare Stage-B trajectory/prefix scores on the same vectors/checkpoint. The adapter's 7500-token tail cap has been checked against the native extractor's `--max_prompt_tokens=7500` default and left truncation; exact event serialization still needs a contract comparison.
4. Verify K=8, observer revision/layer, 60/20/20 stratification algorithm/seed, excluded no-action case 908, optimization and checkpoint selection, and fixed 0.3 README threshold. Report any difference between paper text and executable release.
5. Only after these checks, launch AgentDoG full-1,000 evaluation and the required TRACES K=8 comparisons. A separate K=8 run on the original paired split is useful for shared-data comparisons, but is not the same experiment as the author-algorithm split.

## Task 4: Retain ShieldAgent and defer DreamGuard validation

1. Keep the already verified THU scorer result with the correct project identity and adaptation notes. Native 32k is the user-chosen main context policy; the 25-case YaRN variant stays separate.
2. If a paper-table ShieldAgent baseline uses another prompt or context policy, reproduce that table as a distinct named protocol rather than overwriting the THU-native result.
3. DreamGuard requires an independent train/cal/test manifest before future SafetyDrift testing; previously calibrated test IDs may not be reused as an independent test. Keep it outside the current reproduction comparison until the user-requested method validation is complete.

## Launch conditions and deliverables

- Server `/data1` reported `ENOSPC` during the previous summary write; prepare and verify locally first. Do not redirect downloads/caches to the system drive or delete another user's files. A new server run needs measured free space for its outputs/cache.
- Each formal group needs a committed protocol/config, pinned author code/model, frozen split/policy hashes, successful contract checks and new output directory. Record exact deviations rather than calling an unavailable configuration reproduced.
- Follow the user's preference for one GPU and serial local-model execution; use API concurrency only when it preserves per-trajectory state and timing semantics. No new formal batch has been started by this audit.

## Primary sources

- AgentDoG paper and pinned inference example: https://arxiv.org/html/2605.29801 ; https://github.com/AI45Lab/AgentDoG/blob/c8d803f267a43ec0e103a651265f50f1ff4456d5/examples/getting_started_v1_5.md
- SafePred paper and author release: https://arxiv.org/html/2602.01725v1 ; https://github.com/YurunChen/SafePred/tree/495890eafce02f9990e494493891c4549114a2dc
- TRACES paper and pinned code: https://arxiv.org/html/2605.27690v2 ; https://github.com/lab-flair/TRACES/tree/87579ab60ce6b13f38f7d1f531b6a906656f2748
- THU ShieldAgent model/scorer: https://huggingface.co/thu-coai/ShieldAgent ; https://github.com/thu-coai/Agent-SafetyBench/blob/74feea8de601b3a1449a93fcf70017fe61556f73/score/eval_with_shield.py
- DreamGuard paper and missing-baseline adaptation context: https://arxiv.org/html/2608.05695v1
