#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
batch="${1:?Usage: run-pro-guard-replays.sh BATCH classifiers|safepred GPU}"
lane="${2:?Missing lane}"
gpu="${3:?Missing GPU}"
export PYTHONUNBUFFERED=1
env -u LD_LIBRARY_PATH -u OPENAI_API_KEY -u OPENAI_BASE_URL \
  .venv/bin/python scripts/run-pro-guard-replays.py --batch "$batch" --lane "$lane" --gpu "$gpu" \
  2>&1 | tee -a "$batch/$lane-controller.log"
