#!/usr/bin/env bash
set -euo pipefail

if [ $# -lt 1 ]; then
  echo "Usage: new_project.sh <project-slug>"
  exit 1
fi

slug="$1"
ym="$(date +%Y-%m)"
name="${ym}-${slug}"
base="3 projects/${name}"

if [ -d "$base" ]; then
  echo "Project exists: $base"
  exit 1
fi

cp -R "3 projects/_template-project" "$base"
echo "Created: $base"
