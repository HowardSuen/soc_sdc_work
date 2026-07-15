#!/usr/bin/env bash
# One-shot target-runtime regression for 20_extract_harden_x_if.py
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3}"

exec "$PYTHON_BIN" -B "$SCRIPT_DIR/run_regression.py"
