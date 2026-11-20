#!/usr/bin/env bash
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$root"
export XDG_CACHE_HOME="$root/cache" UV_CACHE_DIR="$root/cache/uv" TMPDIR="$root/cache/tmp" PYTHONUNBUFFERED=1
unset PYTHONPATH LD_LIBRARY_PATH OPENAI_API_KEY OPENAI_BASE_URL
output="${1:?Usage: bash scripts/run-model-diagnostic.sh NEW_OUTPUT [--resume]}"
shift
mkdir -p "$TMPDIR" "$(dirname "$output")"
trap 'status=$?; if [[ -d "$output" ]]; then printf "%s\n" "$status" > "$output/batch.exit"; fi' EXIT
"$root/.venv-agentdojo-author/bin/python" scripts/run-model-diagnostic.py --output "$output" "$@" \
  2>&1 | tee -a "$output.log"
