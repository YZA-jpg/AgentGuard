#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
export CUDA_VISIBLE_DEVICES="${SAFEPRED_AUTHOR_GPU:-3}"
export PYTHONUNBUFFERED=1 OMP_NUM_THREADS=2 TOKENIZERS_PARALLELISM=false
export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True
export HF_HOME="$PWD/cache/huggingface" HF_XET_CACHE="$PWD/cache/xet" TMPDIR="$PWD/cache/tmp"
export XDG_CACHE_HOME="$PWD/cache/xdg" TORCH_HOME="$PWD/cache/torch"
export CUDA_CACHE_PATH="$PWD/cache/cuda" TRITON_CACHE_DIR="$PWD/cache/triton"
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
mkdir -p "$HF_HOME" "$HF_XET_CACHE" "$TMPDIR" "$XDG_CACHE_HOME" "$TORCH_HOME" "$CUDA_CACHE_PATH" "$TRITON_CACHE_DIR"
run="${1:?Usage: bash scripts/run-safepred-safetydrift-only.sh NEW_BATCH_DIRECTORY}"
[[ "$PWD" == /data1/* && "$run" == /data1/* ]] || exit 2
[[ ! -e "$run" ]] || { printf 'Use a new batch directory.\n' >&2; exit 2; }
mkdir -p "$run"
exec 9>"$run/.run.lock"
flock -n 9 || exit 2
exec > >(tee -a "$run/batch.log") 2>&1
trap 'status=$?; printf "%s\n" "$status" > "$run/batch.exit"' EXIT
policy=policies/frozen/safepred-author-qwen3-8b-20261120/safetydrift.json
py=(env -u LD_LIBRARY_PATH -u OPENAI_API_KEY -u OPENAI_BASE_URL .venv/bin/python -u)
printf 'safetydrift\n' > "$run/stage.txt"
"${py[@]}" -m agentguard.safepred_author_eval --benchmark safetydrift --mode formal \
  --split-manifest splits/safetydrift-public-v1.json \
  --policy-file "$policy" --out-dir "$run/safetydrift-formal"
"${py[@]}" scripts/verify-safepred-author.py --run-dir "$run/safetydrift-formal" \
  2>&1 | tee "$run/verification.log"
printf 'complete\n' > "$run/stage.txt"
date -u +%Y-%m-%dT%H:%M:%SZ > "$run/batch.done"
