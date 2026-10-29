#!/bin/bash
# run_remaining_loads.sh
# Sequentially loads DS1, DS4, DS5 (raw + cleaned each) into Snowflake.
# Runs after DS3 is confirmed complete.
# All output logged to data/load_log.txt

# Set credentials via environment variables or .env file before running.
# See .env.example for the required variables.
# Example:
#   export SNOWFLAKE_ACCOUNT="xy12345.us-east-1"
#   export SNOWFLAKE_USER="myuser"
#   export SNOWFLAKE_PASSWORD="mypassword"
#   export SNOWFLAKE_WAREHOUSE="COMPUTE_WH"
#   export SNOWFLAKE_ROLE="SYSADMIN"
if [ -f "$(dirname "$0")/../.env" ]; then
  set -a && source "$(dirname "$0")/../.env" && set +a
fi

LOG="$(dirname "$0")/../data/load_log.txt"
PY="python3"
LOADER="$(dirname "$0")/load_to_snowflake.py"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG"; }

log "================================================"
log "SpotterPrep — Remaining loads: DS1, DS4, DS5"
log "================================================"

for DS in 1 4 5; do
    log "--- Starting Dataset $DS ---"
    $PY "$LOADER" --dataset $DS 2>&1 | tee -a "$LOG"
    EXIT=${PIPESTATUS[0]}
    if [ $EXIT -eq 0 ]; then
        log "--- Dataset $DS COMPLETED OK ---"
    else
        log "--- Dataset $DS FAILED (exit $EXIT) ---"
    fi
done

log "================================================"
log "All remaining loads finished."
log "================================================"
