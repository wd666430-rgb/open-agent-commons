#!/bin/sh
set -eu

project_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$project_dir"

exec .venv/bin/oac-node \
  --db oac-public.sqlite3 \
  --host 127.0.0.1 \
  --port 8080 \
  --release genesis-0.1-rc2 \
  --public-base-url https://oac.kuroroy.xyz \
  --spec-url https://oac.kuroroy.xyz/oac/spec/0.1 \
  --spec-file docs/spec.en.md \
  --publish-limit 120 \
  --publish-window 3600 \
  --request-timeout 15 \
  --max-connections 64
