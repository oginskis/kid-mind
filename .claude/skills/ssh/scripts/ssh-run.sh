#!/bin/sh
set -eu

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../../../.." && pwd)"

# Load connection parameters from project .env
if [ -f "${PROJECT_ROOT}/.env" ]; then
  # shellcheck source=/dev/null
  . "${PROJECT_ROOT}/.env"
else
  echo "Error: .env file not found at ${PROJECT_ROOT}/.env" >&2
  exit 1
fi

if [ -z "${SSH_HOST:-}" ] || [ -z "${SSH_USER:-}" ]; then
  echo "Error: SSH_HOST and SSH_USER must be set in .env" >&2
  exit 1
fi

# Sync scripts to remote before executing
"${SCRIPT_DIR}/sync.sh"

CMD="${*:-hostname && uptime}"

ssh -o StrictHostKeyChecking=no -o ConnectTimeout=10 "${SSH_USER}@${SSH_HOST}" "${CMD}"
