#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
parent=${1:?Pass the previous formal result directory}
unset LD_LIBRARY_PATH OPENAI_API_KEY OPENAI_BASE_URL
export PYTHONUNBUFFERED=1 TMPDIR="$PWD/cache/tmp" XDG_CACHE_HOME="$PWD/cache/xdg"
run=${RAW_RETRY_RUN_DIR:-results/atbench-pro-raw-retry-$(TZ=Asia/Shanghai date +%Y%m%d_%H%M%S)}
mkdir -p "$run" "$TMPDIR" "$XDG_CACHE_HOME"
exec > >(tee -a "$run/batch.log") 2>&1
.venv/bin/python - "$run" "$parent" <<'PY'
from datetime import datetime,timezone
import json
from pathlib import Path
import sys
Path('cache/atbench-pro-raw-retry-active.json').write_text(json.dumps({
    'run_dir':str(Path(sys.argv[1]).resolve()),
    'merged_dir':str((Path(sys.argv[1])/'merged').resolve()),
    'parent':str(Path(sys.argv[2]).resolve()),
    'started_utc':datetime.now(timezone.utc).isoformat(),
},indent=2)+'\n')
PY
status=1
trap 'printf "%s\n" "$status" > "$run/batch.exit"' EXIT
.venv/bin/python -m agentguard.atbench_pro_raw_retry --parent "$parent" --out-dir "$run/merged" \
  --env-file "${RAW_ENV_FILE:-/data1/yaoziao/IPIGuard/.env}" --min-gap 3 --base-delay 10 --max-rate-retries 5
date -u +%Y-%m-%dT%H:%M:%SZ > "$run/batch.done"
status=0
