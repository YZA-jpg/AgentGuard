#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
export CUDA_VISIBLE_DEVICES=${SHIELD_GPU:-3}
export PYTHONUNBUFFERED=1 OMP_NUM_THREADS=2 TOKENIZERS_PARALLELISM=false
export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True
export HF_HOME="$PWD/cache/huggingface" HF_XET_CACHE="$PWD/cache/xet" TMPDIR="$PWD/cache/tmp"
export XDG_CACHE_HOME="$PWD/cache" TORCH_HOME="$PWD/cache/torch" CUDA_CACHE_PATH="$PWD/cache/cuda"
export TRITON_CACHE_DIR="$PWD/cache/triton"
mkdir -p "$HF_HOME" "$HF_XET_CACHE" "$TMPDIR" "$TORCH_HOME" "$CUDA_CACHE_PATH" "$TRITON_CACHE_DIR"
run=${SHIELD_RUN_DIR:-results/atbench-shieldagent-thu-$(TZ=Asia/Shanghai date +%Y%m%d_%H%M%S)}
mkdir -p "$run"
exec > >(tee -a "$run/batch.log") 2>&1
py=(env -u LD_LIBRARY_PATH .venv/bin/python)
"${py[@]}" -m agentguard.shieldagent_eval --out-dir "$run/smoke" --smoke
"${py[@]}" -m agentguard.shieldagent_eval --out-dir "$run/long-native-check" --case-id 426 --mlp-chunk-size 1024
extra=()
if [[ -n ${SHIELD_REUSE_RESULTS:-} ]]; then extra=(--reuse-results "$SHIELD_REUSE_RESULTS"); fi
status=0
"${py[@]}" -m agentguard.shieldagent_eval --out-dir "$run/formal" "${extra[@]}" || status=1
"${py[@]}" -m agentguard.shieldagent_eval --out-dir "$run/yarn-long25" --context-mode yarn128k --only-overlong --mlp-chunk-size 1024 || status=1
exit "$status"
