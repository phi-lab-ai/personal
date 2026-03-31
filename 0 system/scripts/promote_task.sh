#!/usr/bin/env bash
set -euo pipefail

if [ $# -ne 2 ]; then
  echo "Usage: promote_task.sh <file> <review|archive>"
  exit 1
fi

src="$1"
target="$2"

case "$target" in
  review) dest="1 review" ;;
  archive) dest="1 archive" ;;
  *) echo "Target must be review or archive"; exit 1 ;;
esac

mv "$src" "$dest/"
echo "Moved to $dest"
