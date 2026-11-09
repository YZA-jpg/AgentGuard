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

The scorer records label, prediction and latency per case, with accuracy, F1, recall and FPR in the summary. Gold labels and reasons stay in the scoring process. [Official dataset](https://huggingface.co/datasets/AI45Research/ATBench)

## AgentDojo

```bash
.venv/bin/python -m agentguard agentdojo \
  --ipiguard-root /data1/yaoziao/IPIGuard \
  --mode under_attack --suite workspace --user-task-id 0 --injection-task-id 0 \
  --guard-model models/agentdog-0.8b --output results/agentdojo-smoke.jsonl
```

Use `--method none` and `--method ipiguard` for the reference configurations. Select `--mode benign` for normal-task utility. The default live limit is one case per requested suite. Use an explicit `--all-cases` for a full run. The runner uses v1.2.2 and excludes Workspace user task 25, as in the prior experiment.

For each proposed action, the runtime records the guard verdict and latency. `HOLD` and `BLOCK` return a tool error without executing the action. A guard error terminates the current case and is counted separately. The benchmark computes utility and attack success using the original checkers. The output path must be new for every run.

## Tests

```bash
IPIGUARD_ROOT=/data1/yaoziao/IPIGuard .venv/bin/python -m unittest discover -s tests -v
```

Model weights, raw datasets, environment files and result logs are stored outside Git history.
