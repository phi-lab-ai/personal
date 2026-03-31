#!/usr/bin/env bash
set -euo pipefail

echo "=== Weekly Review ==="
echo "Todo:   $(find '1 todo' -type f | wc -l | tr -d ' ')"
echo "Review: $(find '1 review' -type f | wc -l | tr -d ' ')"
echo "Archive:$(find '1 archive' -type f | wc -l | tr -d ' ')"
echo "Projects:$(find '3 projects' -mindepth 1 -maxdepth 1 -type d | wc -l | tr -d ' ')"
