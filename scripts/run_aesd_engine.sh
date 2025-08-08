#!/usr/bin/env bash
# run_aesd_engine.sh
set -euo pipefail
REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_DIR"
echo "Running AESD engine in $REPO_DIR"
python "aesd_agent_engine.py"
