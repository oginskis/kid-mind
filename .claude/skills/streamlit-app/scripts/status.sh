#!/usr/bin/env bash
# Check the status of kid-mind services (Streamlit + ChromaDB).
#
# Usage:  ./status.sh

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")/../../../.." && pwd)"

# Read ChromaDB config from .env
if [[ -f "$PROJECT_ROOT/.env" ]]; then
    CHROMADB_HOST=$(grep -E '^CHROMADB_HOST=' "$PROJECT_ROOT/.env" | cut -d= -f2 | tr -d '[:space:]')
    CHROMADB_PORT=$(grep -E '^CHROMADB_PORT=' "$PROJECT_ROOT/.env" | cut -d= -f2 | tr -d '[:space:]')
fi
CHROMADB_HOST="${CHROMADB_HOST:-localhost}"
CHROMADB_PORT="${CHROMADB_PORT:-8000}"

echo "=== kid-mind service status ==="
echo ""

# Streamlit
ST_PIDS=$(lsof -ti :8501 -sTCP:LISTEN 2>/dev/null || true)
if [[ -n "$ST_PIDS" ]]; then
    echo "Streamlit:  RUNNING (PID $ST_PIDS) on http://localhost:8501"
else
    # Check common alternative ports
    for p in 8502 8503; do
        ST_PIDS=$(lsof -ti :"$p" -sTCP:LISTEN 2>/dev/null || true)
        if [[ -n "$ST_PIDS" ]]; then
            CMD=$(ps -p "$ST_PIDS" -o command= 2>/dev/null || echo "")
            if echo "$CMD" | grep -q "streamlit"; then
                echo "Streamlit:  RUNNING (PID $ST_PIDS) on http://localhost:${p}"
                break
            fi
        fi
    done
    if [[ -z "$ST_PIDS" ]]; then
        echo "Streamlit:  NOT RUNNING"
    fi
fi

# ChromaDB
if curl -sf --max-time 3 "http://${CHROMADB_HOST}:${CHROMADB_PORT}/api/v1/heartbeat" > /dev/null 2>&1; then
    echo "ChromaDB:   RUNNING at ${CHROMADB_HOST}:${CHROMADB_PORT}"
else
    echo "ChromaDB:   NOT REACHABLE at ${CHROMADB_HOST}:${CHROMADB_PORT}"
fi

# .env
if [[ -f "$PROJECT_ROOT/.env" ]]; then
    echo ".env:       PRESENT"
else
    echo ".env:       MISSING (copy .env.example)"
fi

echo ""
