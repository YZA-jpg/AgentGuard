#!/usr/bin/env bash
# Prepared for user launch; no background monitoring is started by this script.
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$root"
export XDG_CACHE_HOME="$root/cache"
export UV_CACHE_DIR="$root/cache/uv"
export TMPDIR="$root/cache/tmp"
export PYTHONUNBUFFERED=1
unset PYTHONPATH LD_LIBRARY_PATH OPENAI_API_KEY OPENAI_BASE_URL
python="$root/.venv-agentdojo-author/bin/python"
output="${1:?Usage: bash scripts/run-reference-pro.sh NEW_OUTPUT [--resume]}"
shift
mkdir -p "$(dirname "$output")" "$TMPDIR"
if [[ -e "$output" && " $* " != *" --resume "* ]]; then
  printf 'Output exists; use a new directory or --resume with identical settings.\n' >&2
  exit 2
fi
args=(--model deepseek-v4-pro --attack-model-name "Deepseek v4 Pro"
      --workers "${PRO_REFERENCE_WORKERS:-4}" --temperature provider --thinking provider
      --exclude-user-task slack:7 --exclude-user-task slack:17
      --stage capability --stage under_attack --env-file "$root/.env")
"$python" scripts/check-pro-reference.py --reference-root "$root/deepseek_result" \
  --output "$output.reference.json" 2>&1 | tee -a "$output.log"
if [[ ! -d "$output" ]]; then
  smoke_resume=()
  if [[ -d "$output-smoke" && " $* " == *" --resume "* ]]; then
    smoke_resume=(--resume)
  fi
  "$python" -m agentguard.native_agentdojo run "${args[@]}" \
    --limit-per-suite 1 --output "$output-smoke" "${smoke_resume[@]}" 2>&1 | tee -a "$output.log"
  "$python" scripts/verify-official-dojo.py "$output-smoke" 2>&1 | tee -a "$output.log"
fi
trap 'status=$?; if [[ -d "$output" ]]; then printf "%s\n" "$status" > "$output/batch.exit"; fi' EXIT
"$python" -m agentguard.native_agentdojo run "${args[@]}" --output "$output" "$@" \
  2>&1 | tee -a "$output.log"
"$python" scripts/verify-official-dojo.py "$output" 2>&1 | tee -a "$output.log"
