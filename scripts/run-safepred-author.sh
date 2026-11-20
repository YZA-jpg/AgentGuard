#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
export CUDA_VISIBLE_DEVICES=${SAFEPRED_AUTHOR_GPU:-4}
export PYTHONUNBUFFERED=1 OMP_NUM_THREADS=2 TOKENIZERS_PARALLELISM=false
export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True
export HF_HOME="$PWD/cache/huggingface" HF_XET_CACHE="$PWD/cache/xet" TMPDIR="$PWD/cache/tmp"
export XDG_CACHE_HOME="$PWD/cache/xdg" TORCH_HOME="$PWD/cache/torch"
export CUDA_CACHE_PATH="$PWD/cache/cuda" TRITON_CACHE_DIR="$PWD/cache/triton"
mkdir -p "$HF_HOME" "$HF_XET_CACHE" "$TMPDIR" "$XDG_CACHE_HOME" "$TORCH_HOME" "$CUDA_CACHE_PATH" "$TRITON_CACHE_DIR"
run=${SAFEPRED_AUTHOR_RUN:-results/safepred-author-qwen3-8b-$(TZ=Asia/Shanghai date +%Y%m%d_%H%M%S)}
mkdir -p "$run"
exec > >(tee -a "$run/batch.log") 2>&1
py=(env -u LD_LIBRARY_PATH -u OPENAI_API_KEY -u OPENAI_BASE_URL .venv/bin/python -u)
status=0
for benchmark in atbench safetydrift; do
    if [[ $benchmark == atbench ]]; then
        source=policies/sources/atbench-author-taxonomy.txt
    else
        source=policies/sources/safetydrift-author-global-rules.txt
    fi
    "${py[@]}" -m agentguard.safepred_author_eval --benchmark "$benchmark" --mode prepare-policy \
        --policy-source "$source" --out-dir "$run/$benchmark-policy"
    "${py[@]}" -m agentguard.safepred_author_eval --benchmark "$benchmark" --mode smoke \
        --policy-file "$run/$benchmark-policy/policies.json" --out-dir "$run/$benchmark-smoke"
    "${py[@]}" -m agentguard.safepred_author_eval --benchmark "$benchmark" --mode formal \
        --policy-file "$run/$benchmark-policy/policies.json" --out-dir "$run/$benchmark-formal" || status=1
done
exit "$status"
