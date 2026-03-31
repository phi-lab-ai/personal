#!/usr/bin/env bash
set -euo pipefail

python3 "0 system/scripts/inbox_process.py" "$@"
