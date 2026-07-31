#!/bin/sh
set -eu

DATA_DIR=/app/server/data
mkdir -p "$DATA_DIR/uploads" "$DATA_DIR/backups"

if [ ! -f "$DATA_DIR/.permissions-ready" ]; then
  chown -R baby-growth:baby-growth "$DATA_DIR"
  touch "$DATA_DIR/.permissions-ready"
  chown baby-growth:baby-growth "$DATA_DIR/.permissions-ready"
fi

exec gosu baby-growth "$@"
