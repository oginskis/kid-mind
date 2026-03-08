#!/bin/sh
# Provision Workload Identity for the chunker K8s Job.
#
# Creates:
#   1. GCP service account: kid-mind-chunker@alteronic-ai.iam.gserviceaccount.com
#   2. Grants it objectViewer on gs://kid-mind-data
#   3. K8s service account "chunker" in namespace kid-mind
#   4. Binds GCP SA <-> K8s SA via Workload Identity
#
# Prerequisites:
#   - gcloud authenticated with owner/editor role
#   - kubectl context set to the alteronic-ai cluster
#   - Namespace kid-mind exists
#
# Usage:
#   ./scripts/setup-workload-identity.sh
set -eu

PROJECT="alteronic-ai"
NAMESPACE="kid-mind"
KSA_NAME="chunker"
GSA_NAME="kid-mind-chunker"
GSA_EMAIL="${GSA_NAME}@${PROJECT}.iam.gserviceaccount.com"
BUCKET="kid-mind-data"

echo "=== Workload Identity setup for chunker job ==="

# 1. Create GCP service account (idempotent)
if gcloud iam service-accounts describe "$GSA_EMAIL" --project="$PROJECT" >/dev/null 2>&1; then
    echo "GCP SA ${GSA_EMAIL} already exists"
else
    echo "Creating GCP SA ${GSA_EMAIL}..."
    gcloud iam service-accounts create "$GSA_NAME" \
        --display-name="kid-mind chunker (GCS read)" \
        --project="$PROJECT"
fi

# 2. Grant objectViewer on the bucket
echo "Granting storage.objectViewer on gs://${BUCKET}..."
gcloud storage buckets add-iam-policy-binding "gs://${BUCKET}" \
    --member="serviceAccount:${GSA_EMAIL}" \
    --role="roles/storage.objectViewer" \
    --quiet

# 3. Create K8s service account with Workload Identity annotation
echo "Creating K8s SA ${KSA_NAME} in namespace ${NAMESPACE}..."
kubectl create serviceaccount "$KSA_NAME" \
    --namespace="$NAMESPACE" \
    --dry-run=client -o yaml | \
    kubectl apply -f -

kubectl annotate serviceaccount "$KSA_NAME" \
    --namespace="$NAMESPACE" \
    "iam.gke.io/gcp-service-account=${GSA_EMAIL}" \
    --overwrite

# 4. Allow K8s SA to impersonate GCP SA
echo "Binding Workload Identity..."
PROJECT_NUMBER=$(gcloud projects describe "$PROJECT" --format='value(projectNumber)')
gcloud iam service-accounts add-iam-policy-binding "$GSA_EMAIL" \
    --project="$PROJECT" \
    --role="roles/iam.workloadIdentityUser" \
    --member="principal://iam.googleapis.com/projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/${PROJECT}.svc.id.goog/subject/ns/${NAMESPACE}/sa/${KSA_NAME}" \
    --quiet

echo "=== Done. K8s SA '${KSA_NAME}' in '${NAMESPACE}' can read gs://${BUCKET} ==="
