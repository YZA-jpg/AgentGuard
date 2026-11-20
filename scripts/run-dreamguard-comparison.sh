#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
export PYTHONUNBUFFERED=1 OMP_NUM_THREADS=2 TOKENIZERS_PARALLELISM=false
export CUDA_VISIBLE_DEVICES="${DREAMGUARD_GPU:-3}"
export HF_HOME="$PWD/cache/huggingface" XDG_CACHE_HOME="$PWD/cache/xdg"
export TORCH_HOME="$PWD/cache/torch" TMPDIR="$PWD/cache/tmp"
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
mkdir -p "$HF_HOME" "$XDG_CACHE_HOME" "$TORCH_HOME" "$TMPDIR"
run="${DREAMGUARD_COMPARISON_DIR:?Set DREAMGUARD_COMPARISON_DIR to a new directory under /data1}"
run=$(realpath -m "$run")
[[ "$PWD" == /data1/* && "$run" == /data1/* ]] || exit 2
mkdir -p "$run"
exec 9>"$run/.run.lock"
flock -n 9 || { printf 'This comparison is already running.\n' >&2; exit 2; }
env -u LD_LIBRARY_PATH -u OPENAI_API_KEY -u OPENAI_BASE_URL \
  .venv/bin/python scripts/run-dreamguard-comparison.py \
  --root "$PWD" --snapshots "$PWD/vendor/dreamguard-comparison-snapshots" \
  --run-dir "$run" --gpu "$CUDA_VISIBLE_DEVICES" \
  --v1-feature-run "$PWD/results/dreamguard-atbench-method-20261118_154154" \
  2>&1 | tee -a "$run/controller.log"
