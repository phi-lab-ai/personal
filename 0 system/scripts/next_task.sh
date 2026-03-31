#!/usr/bin/env bash
set -euo pipefail

next_file="$(find '1 todo' -maxdepth 1 -type f -name '*.md' | sort | head -n 1)"
if [ -z "$next_file" ]; then
  echo "No pending markdown tasks in 1 todo"
  exit 0
fi

echo "Next task: $next_file"
