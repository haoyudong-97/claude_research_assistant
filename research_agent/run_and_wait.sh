#!/bin/bash
# Generic experiment runner with completion marker.
#
# Usage: bash run_and_wait.sh <experiment_script> <output_dir>
#
# Creates:
#   <output_dir>/.status   — written at start (timestamp, script path)
#   <output_dir>/.done     — written on completion (exit code, timestamp)
#   <output_dir>/training.log — full stdout+stderr log
#
# Claude's polling pattern:
#   # Launch:
#   Bash("bash research_agent/run_and_wait.sh scripts/my_exp.sh checkpoints/my_exp/", run_in_background=true)
#   # Poll:
#   Bash("test -f checkpoints/my_exp/.done && cat checkpoints/my_exp/.done || echo RUNNING")

set -o pipefail

SCRIPT="$1"
OUTPUT_DIR="$2"

if [ -z "$SCRIPT" ] || [ -z "$OUTPUT_DIR" ]; then
    echo "Usage: bash run_and_wait.sh <experiment_script> <output_dir>"
    exit 1
fi

if [ ! -f "$SCRIPT" ]; then
    echo "Error: script not found: $SCRIPT"
    exit 1
fi

mkdir -p "$OUTPUT_DIR"
rm -f "$OUTPUT_DIR/.done"
LOG="$OUTPUT_DIR/training.log"

echo "START=$(date -Iseconds)" > "$OUTPUT_DIR/.status"
echo "SCRIPT=$SCRIPT" >> "$OUTPUT_DIR/.status"
echo "PID=$$" >> "$OUTPUT_DIR/.status"

bash "$SCRIPT" 2>&1 | tee "$LOG"
EXIT_CODE=${PIPESTATUS[0]}

echo "EXIT_CODE=$EXIT_CODE" > "$OUTPUT_DIR/.done"
echo "COMPLETED=$(date -Iseconds)" >> "$OUTPUT_DIR/.done"

exit $EXIT_CODE
