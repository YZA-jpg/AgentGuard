#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
export CUDA_VISIBLE_DEVICES=${TRACES_DIAGNOSTIC_GPU:?Set TRACES_DIAGNOSTIC_GPU to one free GPU index}
[[ $CUDA_VISIBLE_DEVICES =~ ^[0-9]+$ ]] || { echo 'Select exactly one GPU index'; exit 2; }
free=$(nvidia-smi --id="$CUDA_VISIBLE_DEVICES" --query-gpu=memory.free --format=csv,noheader,nounits)
(( free >= ${TRACES_DIAGNOSTIC_MIN_FREE_MIB:-24000} )) || { echo "Only ${free}MiB free; choose a free GPU"; exit 2; }
export PYTHONUNBUFFERED=1 OMP_NUM_THREADS=2 TOKENIZERS_PARALLELISM=false
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True
export HF_HOME="$PWD/cache/huggingface" HF_XET_CACHE="$PWD/cache/xet" TMPDIR="$PWD/cache/tmp"
export XDG_CACHE_HOME="$PWD/cache/xdg" TORCH_HOME="$PWD/cache/torch"
export CUDA_CACHE_PATH="$PWD/cache/cuda" TRITON_CACHE_DIR="$PWD/cache/triton"
mkdir -p "$TMPDIR" "$XDG_CACHE_HOME" "$CUDA_CACHE_PATH" "$TRITON_CACHE_DIR"
run=${TRACES_DIAGNOSTIC_RUN:-results/traces-scenario-disjoint-$(TZ=Asia/Shanghai date +%Y%m%d_%H%M%S)}
mkdir "$run"
run=$(realpath "$run")
exec > >(tee -a "$run/batch.log") 2>&1
finish() {
    rc=$?
    printf '%s\n' "$rc" > "$run/batch.exit"
    if (( rc == 0 )); then
        printf 'finished\n' > "$run/stage.txt"
        date -u +%Y-%m-%dT%H:%M:%SZ > "$run/batch.done"
    fi
}
trap finish EXIT
py=(env -u LD_LIBRARY_PATH -u OPENAI_API_KEY -u OPENAI_BASE_URL .venv/bin/python -u)
data=data/safetydrift/5c55e54b75c9c7ee2037db8f3dbd6ae6a7dab8a8
split=splits/safetydrift-scenario-disjoint-v1.json
printf 'train\n' > "$run/stage.txt"
"${py[@]}" -m agentguard.traces_safetydrift --data-root "$data" --split-manifest "$split" \
    --out-dir "$run/trained" --observer models/qwen3-4b-observer --upstream vendor/TRACES
printf 'evaluate\n' > "$run/stage.txt"
"${py[@]}" -m agentguard.safetydrift_eval --data-root "$data" --split-manifest "$split" \
    --method traces --traces-run "$run/trained" --workers 1 --output "$run/formal.jsonl"
printf 'verify\n' > "$run/stage.txt"
"${py[@]}" -m agentguard.traces_audit --data-root "$data" --split-manifest "$split" \
    --training-run "$run/trained" --evaluation "$run/formal.jsonl" --output "$run/verification.json"
