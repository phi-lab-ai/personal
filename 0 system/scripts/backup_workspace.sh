#!/usr/bin/env bash
set -euo pipefail

stamp="$(date +%Y%m%d-%H%M%S)"
backup_dir="0 system/logs/backups/$stamp"
mkdir -p "$backup_dir"

cp -R "0 system" "$backup_dir/0 system"
cp -R "1 todo" "$backup_dir/1 todo"
cp -R "1 review" "$backup_dir/1 review"
cp -R "1 archive" "$backup_dir/1 archive"
cp -R "3 hubs" "$backup_dir/3 hubs"

echo "Backup created: $backup_dir"
