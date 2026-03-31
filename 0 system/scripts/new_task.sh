#!/usr/bin/env bash
set -euo pipefail

title="${*:-new task}"
date_tag="$(date +%Y-%m-%d)"
slug="$(echo "$title" | tr '[:upper:]' '[:lower:]' | sed -E 's/[^a-z0-9]+/-/g; s/^-+|-+$//g')"
file="1 todo/${date_tag}_${slug}.md"

cp "0 system/templates/task.md" "$file"
sed -i '' "s/^title: \"\"/title: \"$title\"/" "$file"
sed -i '' "s/^due: \"\"/due: \"$(date -v+3d +%Y-%m-%d)\"/" "$file"
echo "Created: $file"
