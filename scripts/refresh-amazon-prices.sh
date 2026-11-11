#!/bin/bash
# Scheduler-ready entrypoint for a daily 7:00 AM America/New_York refresh.
# Do not install this as cron or a routine until there is an explicit GO.
# Credentials are read at runtime from the environment (and optional
# AMAZON_SPAPI_CLIENT_ID_FILE). This script never prints secret values.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
exec python3 "$ROOT/scripts/refresh-amazon-prices.py" --root "$ROOT" "$@"
