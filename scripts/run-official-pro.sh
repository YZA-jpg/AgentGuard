#!/usr/bin/env bash
# Model-only full baseline paired to the historical Flash author-lock batch.
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$root"
export XDG_CACHE_HOME="$root/cache" UV_CACHE_DIR="$root/cache/uv" TMPDIR="$root/cache/tmp"
export PYTHONUNBUFFERED=1
unset PYTHONPATH LD_LIBRARY_PATH OPENAI_API_KEY OPENAI_BASE_URL
python="$root/.venv-agentdojo-author/bin/python"
output="${1:?Usage: bash scripts/run-official-pro.sh NEW_OUTPUT}"
[[ "$root" == /data1/* && "$output" == /data1/* ]] || exit 2
if [[ -e "$output" || -e "$output-smoke" ]]; then
  printf 'Use a fresh output directory.\n' >&2
  exit 2
fi
mkdir -p "$(dirname "$output")" "$TMPDIR"
trap 'status=$?; printf "%s\n" "$status" > "$output.launch.exit"; if [[ -d "$output" ]]; then printf "%s\n" "$status" > "$output/batch.exit"; fi' EXIT
common=(--model deepseek-v4-pro --attack-model-name DeepSeek --workers 4
        --temperature 0 --thinking provider --timeout 180 --case-attempts 2
        --env-file "$root/.env")
"$python" scripts/check-pro-flash-parity.py --output "$output.parity.json"
"$python" -m agentguard.native_agentdojo run "${common[@]}" \
  --stage benign --stage under_attack --limit-per-suite 1 --output "$output-smoke" \
  2>&1 | tee "$output-smoke.log"
"$python" scripts/verify-official-dojo.py "$output-smoke" 2>&1 | tee -a "$output-smoke.log"
"$python" scripts/check-pro-flash-parity.py --smoke-plan "$output-smoke/plan.json" \
  --output "$output.smoke-parity.json"
"$python" -m agentguard.native_agentdojo run "${common[@]}" --output "$output" \
  2>&1 | tee "$output.log"
"$python" scripts/verify-official-dojo.py "$output" 2>&1 | tee -a "$output.log"
printf '0\n' > "$output/batch.exit"
