#!/usr/bin/env bash
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$root"
export UV_CACHE_DIR="$root/cache/uv"
export XDG_CACHE_HOME="$root/cache"
export TMPDIR="$root/cache/tmp"
unset PYTHONPATH
mkdir -p "$TMPDIR"
if [[ ! -x "$root/.venv-agentdojo-official/bin/python" ]]; then
  uv venv --python "${PYTHON_BINARY:-python3}" "$root/.venv-agentdojo-official"
fi
uv pip sync --python "$root/.venv-agentdojo-official/bin/python" requirements-native-dojo.txt
"$root/.venv-agentdojo-official/bin/python" -m agentguard.native_agentdojo inspect --skip-candidate-check
