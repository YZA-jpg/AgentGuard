#!/usr/bin/env bash
# Compatibility entry point. v2 also evaluates the independent SafetyDrift test set.
set -euo pipefail
exec bash "$(dirname "$0")/run-dreamguard-paper.sh" "$@"
