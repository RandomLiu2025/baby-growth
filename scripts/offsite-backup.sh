#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

docker compose exec -T app python -m app.backup_cli create --reason scheduled-offsite

if ! docker compose --profile backup run --rm restic snapshots >/dev/null 2>&1; then
  docker compose --profile backup run --rm restic init
fi

docker compose --profile backup run --rm restic backup /backups
docker compose --profile backup run --rm restic forget --keep-daily 7 --keep-weekly 4 --keep-monthly 12 --prune
docker compose --profile backup run --rm restic check
