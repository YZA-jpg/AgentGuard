#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
export CUDA_VISIBLE_DEVICES=${DREAMGUARD_GPU:-3}
export PYTHONUNBUFFERED=1 OMP_NUM_THREADS=2 TOKENIZERS_PARALLELISM=false
run=${DREAMGUARD_RUN_DIR:-results/dreamguard-atbench-method-$(TZ=Asia/Shanghai date +%Y%m%d_%H%M%S)}
mkdir -p "$run"
printf 'DreamGuard reproduction results %s/%s\n' "$PWD" "$run"
env -u LD_LIBRARY_PATH .venv/bin/python -m agentguard.dreamguard \
  --observer models/qwen3-4b-instruct-2507 \
  --safetydrift-root data/safetydrift/5c55e54b75c9c7ee2037db8f3dbd6ae6a7dab8a8 \
  --data data/ATBench/test.json --split-manifest splits/atbench-v1.json \
  --out-dir "$run" 2>&1 | tee "$run/run.log"
