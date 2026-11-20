# AgentGuard

Evaluate published agent safety methods against recorded ATBench trajectories and live AgentDojo tool calls. The first adapter uses the AgentDoG 1.5 coarse checkpoint. The live input adds the candidate action to the observed prefix, and results identify this protocol as `pre_action`.

## Official AgentDojo workflow

New AgentDojo baseline runs use `.venv-agentdojo-official/bin/python -m agentguard.native_agentdojo`, with an isolated official 0.1.35 installation, benchmark v1.2.2, pinned package hashes and unchanged author prompts/tools/checkers. `bash scripts/run-official-flash.sh NEW_OUTPUT_DIRECTORY` runs Flash-0731 on 97 benign tasks, 35 attack-target capability checks and 949 `important_instructions` cases with four independent API workers, then independently verifies the saved trajectories offline. Full requests/responses, native traces, retries and effective request settings are retained. See [configuration, known adaptations and the running batch](docs/agentdojo-official.md).

The historical `python -m agentguard agentdojo --ipiguard-root ...` interface below retains the IPIGuard fork's prompt defense and modified tools; its results use the legacy protocol. See [the baseline correction](docs/agentdojo-deepseek-result-comparison.md).

## Environment

Use a Python 3.10+ environment with PyTorch and a compatible build for the device. On the server, create a project venv with access to the existing IPIGuard environment.

```bash
cd /data1/yaoziao/agentguard
env -u LD_LIBRARY_PATH /data1/yaoziao/conda-envs/ipiguard-py310/bin/python \
  -m venv --system-site-packages .venv
env -u LD_LIBRARY_PATH .venv/bin/python -m pip install -r requirements-model.txt
```

AgentDojo uses the existing `repro/v122-models` IPIGuard checkout and its OpenAI-compatible configuration. Set `OPENAI_API_KEY` and `OPENAI_BASE_URL` in that checkout's `.env`, or specify a separate file with `--env-file`. Existing environment variables take precedence. For model weights, either use the default official 0.8B model ID or point `--guard-model` at a local snapshot. Pass the snapshot commit with `--revision` when available. The adapter uses greedy decoding with thinking disabled and parses exactly one `<Judgment>` tag. [Official model card](https://huggingface.co/AI45Research/AgentDoG1.5-Qwen3.5-0.8B)

## ATBench

Point `--data` at the official `ATBench/test.json` or `ATBench500/test.json`. Set `--config ATBench500` for the latter. The two configs have separate IDs and should be reported separately.

```bash
.venv/bin/python -m agentguard atbench \
  --data data/ATBench/test.json --case-id 184 --case-id 1 \
  --guard-model models/agentdog-0.8b --output results/atbench-smoke.jsonl
```

The scorer records label, prediction and latency per case, with accuracy, F1, recall and FPR in the summary. Gold labels and reasons stay in the scoring process. Run metadata captures the code and model revisions, library versions, device, and precision. Keep the inference configuration fixed when comparing scores across methods. [Official dataset](https://huggingface.co/datasets/AI45Research/ATBench)

## AgentDojo

```bash
.venv/bin/python -m agentguard agentdojo \
  --ipiguard-root /data1/yaoziao/IPIGuard \
  --mode under_attack --suite workspace --user-task-id 0 --injection-task-id 0 \
  --guard-model models/agentdog-0.8b --output results/agentdojo-smoke.jsonl
```

Use `--method none` and `--method ipiguard` for the reference configurations. Select `--mode benign` for normal-task utility. The default live limit is one case per requested suite. Use an explicit `--all-cases` for a full run. The runner uses v1.2.2 and excludes Workspace user task 25, as in the prior experiment.

For each proposed action, the runtime records the guard verdict and latency. `HOLD` and `BLOCK` return a tool error without executing the action. A guard error terminates the current case and is counted separately. The benchmark computes utility and attack success using the original checkers. The output path must be new for every run.

## Predictive baselines

- `safepred` uses the SafePred prompt structure with DeepSeek-v4-pro on DashScope. It logs forecasts for immediate and longer-term effects, fixed-policy violations, and guidance. The shared executor blocks a policy violation. The ATBench runner uses causal replay and marks a trajectory positive at the first intervention. Pair with `--method agentdog --replay` for a same-protocol comparison. [SafePred paper](https://arxiv.org/html/2602.01725v1)
- `traces` uses the authors' ATBench Stage A mechanism bank and Stage B recurrent auditor. AgentGuard adapts the published trajectories to the upstream event format and extracts Qwen3-4B layer 32 features at action ends. If a trajectory has no tool action, it uses its final recorded response. It fits and calibrates on the frozen training and calibration sets, then scores held-out trajectories from the last state. The AgentDojo adapter scores the current candidate prefix using that same ATBench-trained threshold. [TRACES paper](https://arxiv.org/html/2605.27690v2) · [Upstream code](https://github.com/lab-flair/TRACES)

`scripts/run-baseline.sh` writes one JSONL and one log per evaluation. The ATBench groups use `splits/atbench-v1.json`. The AgentDojo groups run all cases in the specified suites, or all four if no suite is given. Set `TRACES_RUN` to a new output directory for `traces-train`, then reuse it for `atbench-traces` and `dojo traces`. Training requires the pinned upstream checkout at `vendor/TRACES`, pandas, scikit-learn, and the official Qwen3-4B snapshot at `models/qwen3-4b-observer`.

Summaries report mean seconds per successful review. ATBench labels are trajectory-level. AgentDojo reports ASR and utility through its task checkers. A recovery-specific FPR requires labeled recovery actions.

## SafePred author-core retests

Use `SAFEPRED_AUTHOR_GPU=4 SAFEPRED_AUTHOR_POLICY_DIR=policies/frozen/safepred-author-qwen3-8b-20261120 bash scripts/run-safepred-author.sh` for the new author-core path with the frozen, versioned policies. Omit `SAFEPRED_AUTHOR_POLICY_DIR` only to prepare a separate experiment with new extraction outputs. The earlier `--method safepred` entry still identifies the historical **SafePred-prompt** adaptation and is retained for old-run reproducibility; the new launcher uses `agentguard.safepred_author_eval` instead.

The new adapter imports the pinned, unmodified `YurunChen/SafePred` implementation: its complete policy CLI workflow, prediction prompt, JSON parser, risk scoring, seven-action history manager and one-candidate root filtering. It uses original Qwen3-8B locally because Qwen3-Max is unavailable on the configured API. This is the paper's Qwen3-8B backbone variant, not its distilled SafePred-8B checkpoint. Enable both prediction horizons, temperature 0.3 and native risk penalty/threshold 0.8/0.7.

Run `scripts/download-safepred-model.py` on the server to obtain and verify the pinned backbone under data1. The launcher freezes benchmark-specification policies, checks reserved calibration cases, and serially retests ATBench's fixed 200 heldout trajectories and SafetyDrift's original 72 test trajectories. Logs contain actual author prompts/outputs, failed attempts, latency, token use and context truncation. This offline risk-evaluation path does not execute online action regeneration or replanning. See [the exact protocol](docs/plans/2026-11-20-safepred-author-retest.md).

## DreamGuard method reproduction

`bash scripts/run-dreamguard-atbench.sh` trains an independent DreamGuard implementation on the public SafetyDrift training split, calibrates on its original test split, and evaluates the frozen ATBench heldout split. Set `DREAMGUARD_GPU` to the GPU index. The encoder snapshot is `models/qwen3-4b-instruct-2507`.

Each run records code hashes, data hashes, calibration settings and implementation differences in `manifest.json`. Metrics and per-trajectory risk scores are written to `atbench.jsonl`. The detailed protocol is in [the reproduction plan](docs/plans/2026-11-17-shieldagent-dreamguard-safetydrift.md).

## SafetyDrift

`SAFETYDRIFT_GPU=3 bash scripts/run-safetydrift-baselines.sh` runs Flash direct classification, AgentDoG 1.5 4B, SafePred-prompt and TRACES on the pinned public release. All methods review the existing Claude Sonnet trajectories; this does not collect new Flash agent trajectories. The author test set stays at 72 cases (38 unsafe, 34 safe). After removing six duplicate development records, 222 cases train TRACES and 57 calibrate/select it. The original test IDs, source hashes and duplicate removals are frozen in `splits/safetydrift-public-v1.json`.

TRACES reuses the author's unmodified Stage-A/Stage-B code, official Qwen3-4B layer-32 observer, K=8 and 30/30 epochs. No matching author SafetyDrift checkpoint was found. Every source decision, including a text response, is represented at its action boundary. This dataset adapter and calibration are recorded separately from author-published results. AgentDoG and Flash share the author coarse prompt with a documented pre-action wrapper; SafePred keeps the existing prompt adaptation.

The launcher first checks two calibration cases per model, then evaluates all 72 test cases. API trajectories use four workers; local models run serially on one GPU. Each JSONL stores visible inputs, model outputs, retries and wall-clock audit latency. Summaries report trajectory F1/recall/FPR plus PHIR and MAS against the author's first risk-level-4 boundary. Recovery FPR remains null because the release has no dedicated recovery labels. See [the implementation plan](docs/plans/2026-11-18-safetydrift-baselines.md).

## THU ShieldAgent on ATBench

`SHIELD_GPU=3 bash scripts/run-shieldagent-atbench.sh` uses the official `thu-coai/ShieldAgent` Qwen2.5-7B checkpoint and the pinned THU scorer prompt/greedy 10-token configuration. It runs a two-case calibration smoke and classifies all 1,000 ATBench trajectories, with a separate paired-200 summary from the same outputs. This is the Agent-SafetyBench scorer, a different project from the ICML policy-reasoning system of the same name.

The dataset adapter maps ATBench roles and tool descriptions into the author's input format. Execution uses FP16/SDPA, batch 1, full attention prefill and no torch.compile. The primary result respects the native 32768-token window, reserving 10 tokens for generation and preserving chat-template boundaries. The 25 overlong cases also receive a separate official-Qwen-YaRN-config comparison capped at 131072 total tokens, with token-independent FFN chunks to limit memory. The runtime records prompt versions, outputs, truncation and wall-clock audit latency. Weights, cache and results remain under the data1 project directory. See [the protocol and comparison audit](docs/plans/2026-11-19-audit-shieldagent-atbench.md).

## Tests

```bash
IPIGUARD_ROOT=/data1/yaoziao/IPIGuard .venv/bin/python -m unittest discover -s tests -v
```

Model weights, raw datasets, environment files and result logs are stored outside Git history.
