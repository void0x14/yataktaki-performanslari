#!/bin/sh
set -eu
DB=${1:-var/db/pipeline.sqlite3}
ROOT=${2:-var/archive}
NAME=${3:-hourly-$(date -u +%Y%m%dT%H%M%SZ).sqlite3}
python3 -m proxy_pipeline.cli.main backup "$DB" "$ROOT" --name "$NAME"
