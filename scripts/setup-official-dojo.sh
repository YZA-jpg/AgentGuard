#!/usr/bin/env bash
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$root"
export UV_CACHE_DIR="$root/cache/uv"
export XDG_CACHE_HOME="$root/cache"
export TMPDIR="$root/cache/tmp"
unset PYTHONPATH
mkdir -p "$TMPDIR"
if [[ ! -x "$root/.venv-agentdojo-author/bin/python" ]]; then
  uv venv --python "${PYTHON_BINARY:-python3}" "$root/.venv-agentdojo-author"
fi
uv pip sync --python "$root/.venv-agentdojo-author/bin/python" --require-hashes requirements-native-dojo-author.txt
"$root/.venv-agentdojo-author/bin/python" -m agentguard.native_agentdojo inspect --skip-candidate-check
