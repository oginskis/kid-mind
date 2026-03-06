#!/usr/bin/env bash
# Stop any running kid-mind Streamlit instance.
#
# Usage:  ./stop.sh

set -euo pipefail

stopped=0

for port in 8501 8502 8503; do
    PIDS=$(lsof -ti :"$port" -sTCP:LISTEN 2>/dev/null || true)
    for pid in $PIDS; do
        CMD=$(ps -p "$pid" -o command= 2>/dev/null || echo "")
        if echo "$CMD" | grep -q "streamlit"; then
            echo "Stopping Streamlit on port $port (PID $pid)..."
            kill "$pid" 2>/dev/null || true
            stopped=1
        fi
    done
done

if [[ "$stopped" -eq 0 ]]; then
    echo "No running Streamlit instance found."
else
    sleep 1
    echo "Done."
fi
