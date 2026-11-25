#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
export PYTHONUNBUFFERED=1 OMP_NUM_THREADS=2 TOKENIZERS_PARALLELISM=false
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True
export HF_HOME="$PWD/cache/huggingface" HF_XET_CACHE="$PWD/cache/xet" TMPDIR="$PWD/cache/tmp"
export XDG_CACHE_HOME="$PWD/cache/xdg" TORCH_HOME="$PWD/cache/torch"
export CUDA_CACHE_PATH="$PWD/cache/cuda" TRITON_CACHE_DIR="$PWD/cache/triton"
mkdir -p "$TMPDIR" "$XDG_CACHE_HOME" "$CUDA_CACHE_PATH" "$TRITON_CACHE_DIR"
if [[ -z ${AGENTGUARD_SOURCE_COMMIT:-} && -f cache/safepred-state-source-commit.txt ]]; then
    export AGENTGUARD_SOURCE_COMMIT=$(tr -d '\r\n' < cache/safepred-state-source-commit.txt)
fi
run=${SAFEPRED_STATE_RUN:-results/safepred-state-dev-$(TZ=Asia/Shanghai date +%Y%m%d_%H%M%S)}
policy=${SAFEPRED_STATE_POLICY:-results/safepred-policy-v2-preflight-20261124/safetydrift-policy}
gpus=${SAFEPRED_STATE_GPUS:?Set explicit GPU IDs, e.g. 4,4 for two independent workers}
limit=${SAFEPRED_STATE_LIMIT:-12}
resume=()
if [[ ${SAFEPRED_STATE_RESUME:-0} == 1 ]]; then
    [[ -n ${SAFEPRED_STATE_RUN:-} ]] || { echo 'Resume requires SAFEPRED_STATE_RUN'; exit 2; }
    resume=(--resume)
fi
printf 'Development only: calibration %s, four arms, worker GPUs %s\nOutput: %s\n' "$limit" "$gpus" "$run"
exec env -u LD_LIBRARY_PATH -u OPENAI_API_KEY -u OPENAI_BASE_URL \
    .venv/bin/python -u -m agentguard.safepred_parallel run \
    --root "$PWD" --benchmark safetydrift --scope calibration --limit "$limit" \
    --gpus "$gpus" --policy-dir "$policy" --out-dir "$run" "${resume[@]}"
