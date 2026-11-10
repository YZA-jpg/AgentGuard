# AgentGuard

Evaluate published agent safety methods against recorded ATBench trajectories and live AgentDojo tool calls. The first adapter uses the AgentDoG 1.5 coarse checkpoint. The live input adds the candidate action to the observed prefix, and results identify this protocol as `pre_action`.

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

## Tests

```bash
IPIGUARD_ROOT=/data1/yaoziao/IPIGuard .venv/bin/python -m unittest discover -s tests -v
```

Model weights, raw datasets, environment files and result logs are stored outside Git history.
