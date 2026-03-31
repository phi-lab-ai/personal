#!/usr/bin/env bash
set -euo pipefail

echo "=== Cleanup Audit ==="
echo "Stale todo files (>14 days):"
find "1 todo" -type f -mtime +14 -print || true

echo
echo "Orphan files (non-md in todo/review/archive):"
find "1 todo" "1 review" "1 archive" -type f ! -name '*.md' -print || true
