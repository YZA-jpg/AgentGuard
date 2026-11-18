#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
export CUDA_VISIBLE_DEVICES=${SAFETYDRIFT_GPU:-3}
export PYTHONUNBUFFERED=1 OMP_NUM_THREADS=2 TOKENIZERS_PARALLELISM=false
run=${SAFETYDRIFT_RUN_DIR:-results/safetydrift-baselines-$(TZ=Asia/Shanghai date +%Y%m%d_%H%M%S)}
mkdir -p "$run"
exec > >(tee -a "$run/batch.log") 2>&1
data=data/safetydrift/5c55e54b75c9c7ee2037db8f3dbd6ae6a7dab8a8
split=splits/safetydrift-public-v1.json
py=(env -u LD_LIBRARY_PATH -u OPENAI_API_KEY -u OPENAI_BASE_URL .venv/bin/python)
printf 'SafetyDrift run: %s/%s; physical GPU: %s\n' "$PWD" "$run" "$CUDA_VISIBLE_DEVICES"
if [[ ! -f "$split" ]]; then
  "${py[@]}" -m agentguard.safetydrift_eval --data-root "$data" --split-manifest "$split" --freeze-split
fi
eval_guard() {
  local method=$1 suffix=$2
  shift 2
  "${py[@]}" -m agentguard.safetydrift_eval --data-root "$data" --split-manifest "$split" \
    --method "$method" --output "$run/$method-$suffix.jsonl" "$@" \
    2>&1 | tee "$run/$method-$suffix.log"
}
train_traces() {
  local destination=$1
  shift
  "${py[@]}" -m agentguard.traces_safetydrift --data-root "$data" --split-manifest "$split" \
    --out-dir "$destination" "$@" 2>&1 | tee "$run/$(basename "$destination").log"
}
# Smoke checks use calibration cases; the test split stays untouched until formal runs.
train_traces "$run/traces-smoke" --smoke
eval_guard traces smoke --split calibration --smoke --traces-run "$run/traces-smoke"
eval_guard agentdog smoke --split calibration --smoke
eval_guard flash smoke --split calibration --smoke
eval_guard safepred smoke --split calibration --smoke
printf 'All smoke checks completed. Starting formal groups.\n'
(
  api_status=0
  eval_guard flash formal || api_status=1
  eval_guard safepred formal || api_status=1
  exit "$api_status"
) &
api_pid=$!
local_status=0
eval_guard agentdog formal || local_status=1
if train_traces "$run/traces-trained"; then
  eval_guard traces formal --traces-run "$run/traces-trained" || local_status=1
else
  local_status=1
fi
wait "$api_pid" || local_status=1
"${py[@]}" - "$run" "$local_status" <<'PY'
import json,sys
from pathlib import Path
p=Path(sys.argv[1])
summaries={}
for method in ['flash','agentdog','safepred','traces']:
    f=p/f'{method}-formal.jsonl'
    if f.exists():
        for line in f.read_text().splitlines():
            row=json.loads(line)
            if row.get('record_type')=='overall_summary': summaries[method]=row
result={'status':'complete' if sys.argv[2]=='0' else 'needs_review','methods':summaries}
(p/'summary.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result))
PY
exit "$local_status"
