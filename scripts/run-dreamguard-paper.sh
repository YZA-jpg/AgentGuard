#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
if [[ "$PWD" != /data1/* ]]; then
  printf 'Run this launcher from the server checkout under /data1.\n' >&2
  exit 2
fi
export CUDA_VISIBLE_DEVICES="${DREAMGUARD_GPU:-${CUDA_VISIBLE_DEVICES:-0}}"
export PYTHONUNBUFFERED=1 OMP_NUM_THREADS="${OMP_NUM_THREADS:-2}"
export TOKENIZERS_PARALLELISM=false
export HF_HOME="$PWD/cache/huggingface" XDG_CACHE_HOME="$PWD/cache/xdg"
export TORCH_HOME="$PWD/cache/torch" TMPDIR="$PWD/cache/tmp"
mkdir -p "$HF_HOME" "$XDG_CACHE_HOME" "$TORCH_HOME" "$TMPDIR"
stage="${DREAMGUARD_STAGE:-all}"
run="${DREAMGUARD_RUN_DIR:-$PWD/results/dreamguard-paper-v2-$(TZ=Asia/Shanghai date +%Y%m%d_%H%M%S)}"
run=$(realpath -m "$run")
if [[ "$run" != /data1/* ]]; then
  printf 'DREAMGUARD_RUN_DIR must resolve under /data1.\n' >&2
  exit 2
fi
mkdir -p "$run"
# One process owns each checkpoint/cache directory; training stages depend on each other.
exec 9>"$run/.run.lock"
flock -n 9 || { printf 'This DreamGuard run directory is already in use.\n' >&2; exit 2; }
stamp=$(TZ=Asia/Shanghai date +%Y%m%d_%H%M%S)
printf 'DreamGuard method reproduction; stage=%s GPU=%s output=%s\n' "$stage" "$CUDA_VISIBLE_DEVICES" "$run"
env -u LD_LIBRARY_PATH .venv/bin/python -m agentguard.dreamguard \
  --stage "$stage" \
  --observer models/qwen3-4b-instruct-2507 \
  --safetydrift-root data/safetydrift/5c55e54b75c9c7ee2037db8f3dbd6ae6a7dab8a8 \
  --safetydrift-split splits/safetydrift-public-v1.json \
  --data data/ATBench/test.json --split-manifest splits/atbench-v1.json \
  --atbench-scope "${DREAMGUARD_ATBENCH_SCOPE:-all}" \
  --evaluation "${DREAMGUARD_EVALUATION:-both}" \
  --latency "${DREAMGUARD_LATENCY:-end-to-end}" \
  --eval-latent "${DREAMGUARD_EVAL_LATENT:-argmax}" \
  --output-tag "$stamp" --out-dir "$run" "$@" \
  2>&1 | tee "$run/${stage}-${stamp}.log"
