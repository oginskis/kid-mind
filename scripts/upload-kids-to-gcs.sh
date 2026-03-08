#!/bin/sh
# Upload KID PDFs and ISIN metadata from the remote box to GCS.
#
# The remote box has no gcloud, so this script:
#   1. Tars the data on the box via SSH
#   2. Streams the tar through a pipe (nothing stored locally)
#   3. Extracts and uploads individual files to GCS
#
# Usage:
#   ./scripts/upload-kids-to-gcs.sh           # upload kids/ and isins/
#   ./scripts/upload-kids-to-gcs.sh --dry-run # show what would be uploaded
set -eu

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Load SSH connection from .env
if [ -f "$PROJECT_ROOT/.env" ]; then
    SSH_HOST=$(grep '^SSH_HOST=' "$PROJECT_ROOT/.env" | cut -d= -f2)
    SSH_USER=$(grep '^SSH_USER=' "$PROJECT_ROOT/.env" | cut -d= -f2)
fi

: "${SSH_HOST:?Set SSH_HOST in .env}"
: "${SSH_USER:?Set SSH_USER in .env}"

BUCKET="gs://kid-mind-data"
REMOTE_DATA="\$HOME/kid-mind/data"
DRY_RUN=false

if [ "${1:-}" = "--dry-run" ]; then
    DRY_RUN=true
fi

echo "=== Uploading KID data from ${SSH_USER}@${SSH_HOST} to ${BUCKET} ==="

# Use a temp dir for the streamed data
TMPDIR=$(mktemp -d)
trap 'rm -rf "$TMPDIR"' EXIT

echo "Downloading data from remote box..."
# shellcheck disable=SC2029  # $HOME must expand on the remote side
ssh "${SSH_USER}@${SSH_HOST}" "tar cf - -C ${REMOTE_DATA} kids/ isins/" | tar xf - -C "$TMPDIR"

KIDS_COUNT=$(find "$TMPDIR/kids" -name '*.pdf' | wc -l | tr -d ' ')
ISINS_COUNT=$(find "$TMPDIR/isins" -name '*.json' | wc -l | tr -d ' ')
echo "Found ${KIDS_COUNT} PDFs and ${ISINS_COUNT} ISIN files"

if [ "$DRY_RUN" = "true" ]; then
    echo "[DRY RUN] Would upload to ${BUCKET}/kids/ and ${BUCKET}/isins/"
    exit 0
fi

echo "Uploading kids/ to ${BUCKET}/kids/ ..."
gcloud storage rsync "$TMPDIR/kids/" "${BUCKET}/kids/" --recursive --project=alteronic-ai

echo "Uploading isins/ to ${BUCKET}/isins/ ..."
gcloud storage rsync "$TMPDIR/isins/" "${BUCKET}/isins/" --recursive --project=alteronic-ai

echo "=== Done. ${KIDS_COUNT} PDFs and ${ISINS_COUNT} ISIN files in ${BUCKET} ==="
