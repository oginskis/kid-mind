---
name: cloud-build
description: Build and push Docker images to Google Artifact Registry using Cloud Build. Use this skill whenever the user wants to build a container image, push to GCR/Artifact Registry, rebuild the app image, deploy a new version, or says things like "build the image", "push to registry", "rebuild and push", "update the container". Also use when the user asks to check build status, list builds, view build logs, verify a pushed image, or troubleshoot Cloud Build failures, permission errors, or Artifact Registry access issues — even if they just say "is the build done?", "what happened to the build?", or "show me recent builds".
---

# Cloud Build: Build & Push Docker Images

Build the kid-mind Docker image and push it to Google Artifact Registry using Google Cloud Build. Cloud Build runs on native amd64 hardware in GCP — no local emulation needed.

## Registry details

- **GCP Project:** `alteronic-ai`
- **Region:** `europe-north1`
- **Repository:** `kid-mind` (Artifact Registry, Docker format)
- **Full image path:** `europe-north1-docker.pkg.dev/alteronic-ai/kid-mind/kid-mind`

## Pre-flight checks

Before submitting a build, verify these in order. Skip checks that have already passed in this session.

### 1. Authentication and correct project

```bash
gcloud auth list  # verify active account
gcloud config get-value project  # should be "alteronic-ai"
```

Test that the token is valid by making an API call:
```bash
gcloud builds list --project=alteronic-ai --limit=1 2>&1
```

If you see `ERROR: ... invalid grant`, `token has been expired`, `UNAUTHENTICATED`, or `Please run: gcloud auth login`:
1. Tell the user their GCP session has expired
2. Ask them to run `gcloud auth login` and complete the browser flow
3. Wait for them to confirm, then retry

### 2. Cloud Build API enabled

```bash
gcloud services list --enabled --filter="name:cloudbuild.googleapis.com" --project=alteronic-ai
```

If not enabled:
```bash
gcloud services enable cloudbuild.googleapis.com --project=alteronic-ai
```

After enabling, wait 60 seconds for IAM propagation before submitting builds.

### 3. Service account permissions

Cloud Build uses two service accounts that both need storage and Artifact Registry access. Get the project number first:

```bash
PROJECT_NUM=$(gcloud projects describe alteronic-ai --format="value(projectNumber)")
```

Required roles (grant if missing):

```bash
# Compute service account — reads source from GCS, pushes images
gcloud projects add-iam-policy-binding alteronic-ai \
  --member="serviceAccount:${PROJECT_NUM}-compute@developer.gserviceaccount.com" \
  --role="roles/storage.admin" --quiet

gcloud projects add-iam-policy-binding alteronic-ai \
  --member="serviceAccount:${PROJECT_NUM}-compute@developer.gserviceaccount.com" \
  --role="roles/artifactregistry.writer" --quiet

# Cloud Build service account — orchestrates the build
gcloud projects add-iam-policy-binding alteronic-ai \
  --member="serviceAccount:${PROJECT_NUM}@cloudbuild.gserviceaccount.com" \
  --role="roles/storage.admin" --quiet

gcloud projects add-iam-policy-binding alteronic-ai \
  --member="serviceAccount:${PROJECT_NUM}@cloudbuild.gserviceaccount.com" \
  --role="roles/artifactregistry.repoAdmin" --quiet
```

After granting new roles, wait 30 seconds before submitting.

### 4. Artifact Registry repository exists

```bash
gcloud artifacts repositories describe kid-mind \
  --location=europe-north1 --project=alteronic-ai --format="value(name)" 2>/dev/null
```

If it doesn't exist:
```bash
gcloud artifacts repositories create kid-mind \
  --repository-format=docker \
  --location=europe-north1 \
  --description="kid-mind ETF research assistant" \
  --project=alteronic-ai
```

## Submit the build

```bash
gcloud builds submit \
  --tag europe-north1-docker.pkg.dev/alteronic-ai/kid-mind/kid-mind:latest \
  --project=alteronic-ai \
  .
```

Run this from the project root (`kid-mind/`). The `.gcloudignore` and `.dockerignore` control what gets uploaded and what goes into the image.

For long builds, run in background and monitor:
```bash
# Submit and capture build ID
BUILD_ID=$(gcloud builds submit \
  --tag europe-north1-docker.pkg.dev/alteronic-ai/kid-mind/kid-mind:latest \
  --project=alteronic-ai \
  --async --format="value(id)" .)

# Monitor progress
gcloud builds log $BUILD_ID --project=alteronic-ai --stream
# Or check status
gcloud builds describe $BUILD_ID --project=alteronic-ai --format="value(status)"
```

## Check build status and history

Use these commands whenever the user asks "is the build done?", "what happened?", "show me builds", etc.

### List recent builds

```bash
gcloud builds list --project=alteronic-ai --limit=5 \
  --format="table(id.slice(0:8),status,createTime.date(tz=LOCAL),duration)"
```

### Check a specific build

```bash
# Status only
gcloud builds describe <BUILD_ID> --project=alteronic-ai --format="value(status)"

# Full details (status, duration, image pushed, errors)
gcloud builds describe <BUILD_ID> --project=alteronic-ai \
  --format="table(status,duration,images,failureInfo.detail)"
```

Possible status values: `QUEUED`, `WORKING`, `SUCCESS`, `FAILURE`, `TIMEOUT`, `CANCELLED`.

### View build logs

```bash
# Full log output
gcloud builds log <BUILD_ID> --project=alteronic-ai

# Just the Dockerfile steps (quick progress check)
gcloud builds log <BUILD_ID> --project=alteronic-ai 2>&1 | grep "^Step"

# Last 20 lines (latest activity)
gcloud builds log <BUILD_ID> --project=alteronic-ai 2>&1 | tail -20
```

### Cancel a build

```bash
gcloud builds cancel <BUILD_ID> --project=alteronic-ai
```

### Verify a pushed image

After a successful build, confirm the image landed in the registry:

```bash
gcloud artifacts docker images list \
  europe-north1-docker.pkg.dev/alteronic-ai/kid-mind/kid-mind \
  --project=alteronic-ai --limit=3 \
  --format="table(package,version.slice(0:12),createTime.date(tz=LOCAL),metadata.imageSizeBytes)"
```

## Common errors and fixes

| Error | Cause | Fix |
|-------|-------|-----|
| `Cloud Build API has not been used` | API not enabled | `gcloud services enable cloudbuild.googleapis.com` + wait 60s |
| `PERMISSION_DENIED: The caller does not have permission` | Freshly enabled API, IAM not propagated | Wait 60s and retry, or grant roles explicitly (see pre-flight step 3) |
| `does not have storage.objects.get access` | Compute SA missing storage role | Grant `roles/storage.admin` to `{NUM}-compute@developer.gserviceaccount.com` |
| `Permission 'artifactregistry.repositories.uploadArtifacts' denied` | Build SA can't push to registry | Grant `roles/artifactregistry.repoAdmin` to `{NUM}@cloudbuild.gserviceaccount.com` |
| `Readme file does not exist: README.md` | Dockerfile doesn't copy README.md but pyproject.toml references it | Add `README.md` to the COPY line with pyproject.toml |
| Build timeout | Image too large or slow network | Use `--timeout=1800s` flag |

## Dockerfile notes

The Dockerfile uses `UV_TORCH_BACKEND=cpu` to avoid downloading ~4GB of CUDA libraries. This is set as an ENV in the Dockerfile — the lockfile is platform-aware and uv respects this at install time.

Key files that must be copied before `uv sync`:
- `pyproject.toml`
- `uv.lock`
- `README.md` (required by hatchling build backend)

## Do NOT use podman for this

Building linux/amd64 images with podman on Apple Silicon requires QEMU emulation, which is extremely slow and prone to I/O errors with large images. Always use Cloud Build — it runs on native amd64 hardware and is faster and more reliable.
