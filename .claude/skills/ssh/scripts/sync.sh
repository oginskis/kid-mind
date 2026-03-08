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

REMOTE_DIR="${1:-~/scripts/}"

# Guardrail: never sync to a data directory on the remote
NORMALIZED_DIR=$(echo "${REMOTE_DIR}" | sed 's:/*$::')
case "${NORMALIZED_DIR}" in
  data|*/data|*/data/*)
    echo "Error: refusing to rsync to a data/ directory on the remote." >&2
    echo "Remote data directories must not be overwritten. Use scp or rsync without --delete." >&2
    exit 1
    ;;
esac

# shellcheck disable=SC2154  # SSH_USER and SSH_HOST come from .env
rsync -avz --delete \
  --exclude='.env' \
  -e "ssh -o StrictHostKeyChecking=accept-new -o ConnectTimeout=10" \
  "${SCRIPT_DIR}/" \
  "${SSH_USER}@${SSH_HOST}:${REMOTE_DIR}"
