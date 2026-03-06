#!/usr/bin/env bash
# Start the kid-mind Streamlit app.
#
# Handles:
#   - Port conflict detection and resolution
#   - ChromaDB health check
#   - .env presence check
#   - Clean shutdown of previous instances
#
# Usage:
#   ./start.sh              # default port 8501
#   ./start.sh --port 8502  # custom port

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")/../../../.." && pwd)"
cd "$PROJECT_ROOT"

PORT=8501

while [[ $# -gt 0 ]]; do
    case "$1" in
        --port) PORT="$2"; shift 2 ;;
        *) echo "Unknown arg: $1"; exit 1 ;;
    esac
done

# ── Preflight checks ────────────────────────────────────────────────────────

# 1. Check .env exists
if [[ ! -f "$PROJECT_ROOT/.env" ]]; then
    echo "ERROR: .env file not found at $PROJECT_ROOT/.env"
    echo "Copy .env.example to .env and fill in the required values."
    exit 1
fi

# 2. Check ChromaDB is reachable
CHROMADB_HOST=$(grep -E '^CHROMADB_HOST=' "$PROJECT_ROOT/.env" | cut -d= -f2 | tr -d '[:space:]')
CHROMADB_PORT=$(grep -E '^CHROMADB_PORT=' "$PROJECT_ROOT/.env" | cut -d= -f2 | tr -d '[:space:]')
CHROMADB_HOST="${CHROMADB_HOST:-localhost}"
CHROMADB_PORT="${CHROMADB_PORT:-8000}"

echo "Checking ChromaDB at ${CHROMADB_HOST}:${CHROMADB_PORT}..."
if ! curl -sf --max-time 5 "http://${CHROMADB_HOST}:${CHROMADB_PORT}/api/v1/heartbeat" > /dev/null 2>&1; then
    echo "ERROR: ChromaDB is not reachable at ${CHROMADB_HOST}:${CHROMADB_PORT}"
    echo ""
    echo "Start it with:  chroma run --host ${CHROMADB_HOST} --port ${CHROMADB_PORT}"
    echo "Or via Docker:  docker run -p ${CHROMADB_PORT}:8000 chromadb/chroma"
    exit 1
fi
echo "  ChromaDB OK"

# 3. Handle port conflicts
if lsof -i :"$PORT" -sTCP:LISTEN > /dev/null 2>&1; then
    PID=$(lsof -ti :"$PORT" -sTCP:LISTEN | head -1)
    CMD=$(ps -p "$PID" -o command= 2>/dev/null || echo "unknown")

    # If it's already our Streamlit app, offer to kill it
    if echo "$CMD" | grep -q "streamlit"; then
        echo "Streamlit is already running on port $PORT (PID $PID)."
        echo "Stopping it..."
        kill "$PID" 2>/dev/null || true
        # Wait up to 5 seconds for clean shutdown
        for i in $(seq 1 10); do
            if ! lsof -i :"$PORT" -sTCP:LISTEN > /dev/null 2>&1; then
                break
            fi
            sleep 0.5
        done
        if lsof -i :"$PORT" -sTCP:LISTEN > /dev/null 2>&1; then
            echo "ERROR: Could not stop previous instance. Kill PID $PID manually."
            exit 1
        fi
        echo "  Previous instance stopped."
    else
        echo "ERROR: Port $PORT is in use by another process (PID $PID): $CMD"
        echo ""
        echo "Options:"
        echo "  1. Stop that process:  kill $PID"
        echo "  2. Use a different port:  $0 --port 8502"
        exit 1
    fi
fi

# 4. Check uv is available
if ! command -v uv &> /dev/null; then
    echo "ERROR: 'uv' is not installed or not in PATH."
    echo "Install it: curl -LsSf https://astral.sh/uv/install.sh | sh"
    exit 1
fi

# ── Launch ───────────────────────────────────────────────────────────────────

echo ""
echo "Starting kid-mind on http://localhost:${PORT}"
echo "Press Ctrl+C to stop."
echo ""

exec uv run streamlit run streamlit_app.py \
    --server.port "$PORT" \
    --server.headless true \
    --browser.gatherUsageStats false
