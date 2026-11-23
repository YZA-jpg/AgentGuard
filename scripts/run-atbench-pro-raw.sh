#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
unset LD_LIBRARY_PATH OPENAI_API_KEY OPENAI_BASE_URL
export PYTHONUNBUFFERED=1
export TMPDIR="$PWD/cache/tmp" XDG_CACHE_HOME="$PWD/cache/xdg"
mkdir -p "$TMPDIR" "$XDG_CACHE_HOME"
run=${RAW_RUN_DIR:-results/atbench-pro-raw-$(TZ=Asia/Shanghai date +%Y%m%d_%H%M%S)}
mkdir -p "$run"
exec > >(tee -a "$run/batch.log") 2>&1
.venv/bin/python - "$run" <<'PY'
from datetime import datetime,timezone
import json
from pathlib import Path
import sys
Path('cache/atbench-pro-raw-active.json').write_text(json.dumps({
    'run_dir':str(Path(sys.argv[1]).resolve()),
    'started_utc':datetime.now(timezone.utc).isoformat(),
    'method':'deepseek-v4-pro-plain-raw-json',
    'formal_cases':200,
},indent=2)+'\n')
PY
status=1
trap 'printf "%s\n" "$status" > "$run/batch.exit"' EXIT
common=(--env-file "${RAW_ENV_FILE:-/data1/yaoziao/IPIGuard/.env}" --model deepseek-v4-pro
        --max-new-tokens 1024 --workers "${RAW_WORKERS:-4}")
.venv/bin/python -m agentguard.atbench_pro_raw run "${common[@]}" --mode smoke --out-dir "$run/smoke"
.venv/bin/python -m agentguard.atbench_pro_raw run "${common[@]}" --mode formal --out-dir "$run/formal"
date -u +%Y-%m-%dT%H:%M:%SZ > "$run/batch.done"
status=0
