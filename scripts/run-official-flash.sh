#!/usr/bin/env bash
# Run after offline tests and smoke verification. All paths stay on data1.
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$root"
export XDG_CACHE_HOME="$root/cache"
export UV_CACHE_DIR="$root/cache/uv"
export TMPDIR="$root/cache/tmp"
export PYTHONUNBUFFERED=1
unset PYTHONPATH LD_LIBRARY_PATH OPENAI_API_KEY OPENAI_BASE_URL
python="$root/.venv-agentdojo-author/bin/python"
output="${1:?Usage: bash scripts/run-official-flash.sh /data1/.../NEW_OUTPUT [additional runner arguments]}"
shift
if [[ -e "$output" && " $* " != *" --resume "* ]]; then
  printf 'Output exists; use a new directory or --resume with identical settings.\n' >&2
  exit 2
fi
mkdir -p "$(dirname "$output")" "$TMPDIR"
trap 'status=$?; if [[ -d "$output" ]]; then printf "%s\n" "$status" > "$output/batch.exit"; fi' EXIT
"$python" -m agentguard.native_agentdojo run \
  --model deepseek-v4-flash-0731 --attack-model-name DeepSeek \
  --workers 4 --temperature 0 --thinking provider \
  --env-file "$root/.env" --output "$output" "$@" \
  2>&1 | tee -a "$output.log"
"$python" scripts/verify-official-dojo.py "$output" 2>&1 | tee -a "$output.log"
