#!/usr/bin/env bash
set -euo pipefail

interval="${1:-20}"
echo "Watching 1 todo every ${interval}s (Ctrl+C to stop)..."
while true; do
  ./"0 system/scripts/inbox_process.sh"
  sleep "$interval"
done
