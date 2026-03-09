#!/bin/sh
# Provision Workload Identity for Vertex AI access.
#
# Sets up the Streamlit pod to call Vertex AI via ADC, and grants the
# existing Chunker GCP SA the same Vertex AI role.
#
# Creates:
#   1. GCP SA kid-mind-streamlit with roles/aiplatform.user
#   2. K8s SA "streamlit" in namespace kid-mind, bound via Workload Identity
#   3. Grants roles/aiplatform.user to existing kid-mind-chunker GCP SA
#
# Prerequisites:
#   - gcloud authenticated with owner/editor role
#   - kubectl context set to the target cluster
#   - Namespace kid-mind exists
#   - Chunker Workload Identity already set up (setup-workload-identity.sh)
#
# Usage:
#   ./scripts/setup-vertex-ai-identity.sh
set -eu

PROJECT="alteronic-ai"
NAMESPACE="kid-mind"

STREAMLIT_KSA="streamlit"
STREAMLIT_GSA="kid-mind-streamlit"
STREAMLIT_GSA_EMAIL="${STREAMLIT_GSA}@${PROJECT}.iam.gserviceaccount.com"

CHUNKER_GSA_EMAIL="kid-mind-chunker@${PROJECT}.iam.gserviceaccount.com"

echo "=== Vertex AI Workload Identity setup ==="

# 1. Create GCP SA for Streamlit (idempotent)
if gcloud iam service-accounts describe "$STREAMLIT_GSA_EMAIL" \
     --project="$PROJECT" >/dev/null 2>&1; then
    echo "GCP SA ${STREAMLIT_GSA_EMAIL} already exists"
else
    echo "Creating GCP SA ${STREAMLIT_GSA_EMAIL}..."
    gcloud iam service-accounts create "$STREAMLIT_GSA" \
        --display-name="kid-mind streamlit (Vertex AI)" \
        --project="$PROJECT"
fi

# 2. Grant aiplatform.user to both SAs
for sa_email in "$STREAMLIT_GSA_EMAIL" "$CHUNKER_GSA_EMAIL"; do
    echo "Granting aiplatform.user to ${sa_email}..."
    gcloud projects add-iam-policy-binding "$PROJECT" \
        --member="serviceAccount:${sa_email}" \
        --role="roles/aiplatform.user" \
        --quiet
done

# 3. Create K8s SA for Streamlit with Workload Identity annotation
echo "Creating K8s SA ${STREAMLIT_KSA} in namespace ${NAMESPACE}..."
kubectl create serviceaccount "$STREAMLIT_KSA" \
    --namespace="$NAMESPACE" \
    --dry-run=client -o yaml | \
    kubectl apply -f -

kubectl annotate serviceaccount "$STREAMLIT_KSA" \
    --namespace="$NAMESPACE" \
    "iam.gke.io/gcp-service-account=${STREAMLIT_GSA_EMAIL}" \
    --overwrite

# 4. Bind K8s SA -> GCP SA via Workload Identity
echo "Binding Workload Identity for Streamlit..."
PROJECT_NUMBER=$(gcloud projects describe "$PROJECT" \
    --format='value(projectNumber)')
gcloud iam service-accounts add-iam-policy-binding "$STREAMLIT_GSA_EMAIL" \
    --project="$PROJECT" \
    --role="roles/iam.workloadIdentityUser" \
    --member="principal://iam.googleapis.com/projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/${PROJECT}.svc.id.goog/subject/ns/${NAMESPACE}/sa/${STREAMLIT_KSA}" \
    --quiet

echo ""
echo "=== Done ==="
echo "Streamlit: K8s SA '${STREAMLIT_KSA}' -> '${STREAMLIT_GSA_EMAIL}' (aiplatform.user)"
echo "Chunker:   '${CHUNKER_GSA_EMAIL}' granted aiplatform.user"
