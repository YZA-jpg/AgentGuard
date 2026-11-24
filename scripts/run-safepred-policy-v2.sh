#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
export CUDA_VISIBLE_DEVICES=${SAFEPRED_V2_GPU:?Set SAFEPRED_V2_GPU to one free GPU index}
[[ $CUDA_VISIBLE_DEVICES =~ ^[0-9]+$ ]] || { echo 'Select exactly one GPU index'; exit 2; }
free=$(nvidia-smi --id="$CUDA_VISIBLE_DEVICES" --query-gpu=memory.free --format=csv,noheader,nounits)
(( free >= ${SAFEPRED_V2_MIN_FREE_MIB:-28000} )) || { echo "Only ${free}MiB free; choose a free GPU"; exit 2; }
export PYTHONUNBUFFERED=1 OMP_NUM_THREADS=2 TOKENIZERS_PARALLELISM=false
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True
export HF_HOME="$PWD/cache/huggingface" HF_XET_CACHE="$PWD/cache/xet" TMPDIR="$PWD/cache/tmp"
export XDG_CACHE_HOME="$PWD/cache/xdg" TORCH_HOME="$PWD/cache/torch"
export CUDA_CACHE_PATH="$PWD/cache/cuda" TRITON_CACHE_DIR="$PWD/cache/triton"
mkdir -p "$TMPDIR" "$XDG_CACHE_HOME" "$CUDA_CACHE_PATH" "$TRITON_CACHE_DIR"
if [[ -z ${AGENTGUARD_SOURCE_COMMIT:-} && -f cache/safepred-policy-v2-source-commit.txt ]]; then
    export AGENTGUARD_SOURCE_COMMIT=$(tr -d '\r\n' < cache/safepred-policy-v2-source-commit.txt)
fi
run=${SAFEPRED_V2_RUN:-results/safepred-policy-v2-$(TZ=Asia/Shanghai date +%Y%m%d_%H%M%S)}
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
benchmarks=${SAFEPRED_V2_BENCHMARKS:-safetydrift agentdojo}
bundle=${SAFEPRED_V2_BUNDLE:-results/agentdojo-pro-guard-replay-20261122_011126/bundle.json}
printf 'Run: %s\nGPU: %s\n' "$run" "$CUDA_VISIBLE_DEVICES"
for benchmark in $benchmarks; do
    [[ $benchmark == safetydrift || $benchmark == agentdojo ]] || { echo 'Unknown benchmark'; exit 2; }
    printf '%s-policy\n' "$benchmark" > "$run/stage.txt"
    policy="$run/$benchmark-policy"
    if [[ -n ${SAFEPRED_V2_POLICY_ROOT:-} ]]; then
        policy=$(realpath "$SAFEPRED_V2_POLICY_ROOT/$benchmark-policy")
    else
        "${py[@]}" -m agentguard.safepred_policy_v2 prepare --benchmark "$benchmark" --out-dir "$policy"
    fi
    "${py[@]}" -m agentguard.safepred_policy_v2 verify --benchmark "$benchmark" --policy-dir "$policy"
    if [[ ${SAFEPRED_V2_PREPARE_ONLY:-0} == 1 ]]; then
        continue
    fi
    printf '%s-formal\n' "$benchmark" > "$run/stage.txt"
    out="$run/$benchmark-formal"
    "${py[@]}" -m agentguard.safepred_policy_v2 evaluate --benchmark "$benchmark" \
        --policy-dir "$policy" --out-dir "$out" --bundle "$bundle"
    if [[ $benchmark == safetydrift ]]; then
        "${py[@]}" scripts/verify-safepred-author.py --run-dir "$out"
    else
        "${py[@]}" -m agentguard.native_replay verify --bundle "$bundle" --out-dir "$out"
    fi
done
