#!/usr/bin/env bash
set -uo pipefail
cd "$(dirname "$0")/.."
run=${1:?Pass a new run directory}
export CUDA_VISIBLE_DEVICES=${2:-3}
unset LD_LIBRARY_PATH OPENAI_API_KEY OPENAI_BASE_URL
export PYTHONUNBUFFERED=1 OMP_NUM_THREADS=2 TOKENIZERS_PARALLELISM=false
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True
export HF_HOME="$PWD/cache/huggingface" HF_XET_CACHE="$PWD/cache/xet" TMPDIR="$PWD/cache/tmp"
export XDG_CACHE_HOME="$PWD/cache/xdg" TORCH_HOME="$PWD/cache/torch" CUDA_CACHE_PATH="$PWD/cache/cuda" TRITON_CACHE_DIR="$PWD/cache/triton"
mkdir -p "$run"
status=0
printf 'agentdog-recovery\n' > "$run/stage.txt"
.venv/bin/python -m agentguard.agentdog_recovery \
  --parent results/guard-makeups-20261122_212027/agentdog-merged \
  --bundle results/agentdojo-pro-guard-replay-20261122_011126/bundle.json \
  --out-dir "$run/agentdog-recovery" > "$run/agentdog-recovery.log" 2>&1 || status=1
printf 'dreamguard-target-calibration\n' > "$run/stage.txt"
.venv/bin/python -m agentguard.dream_transfer \
  --source-run results/dreamguard-v1-v2-20261121_015401/v2 \
  --out-dir "$run/dreamguard-target-calibration" > "$run/dreamguard-target-calibration.log" 2>&1 || status=1
printf '%s\n' "$status" > "$run/batch.exit"
printf 'finished\n' > "$run/stage.txt"
if [[ $status == 0 ]]; then date -u +%Y-%m-%dT%H:%M:%SZ > "$run/batch.done"; fi
exit "$status"
