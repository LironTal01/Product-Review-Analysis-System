#!/usr/bin/env bash
# Deploy PRAS to Azure Container Apps.
#
# Prereqs (one-time):
#   1. az CLI installed:        brew install azure-cli
#   2. Logged in:                az login
#   3. Subscription selected:    az account set --subscription <SUB_ID>
#   4. OPENAI_API_KEY in env (optional — without it /api/analyze still
#      returns the deterministic mock payload).
#
# Usage:
#   chmod +x scripts/azure_deploy.sh           # one-time
#   ./scripts/azure_deploy.sh                  # uses the defaults below
#   RESOURCE_GROUP=my-rg ./scripts/azure_deploy.sh
#
# Overridable env vars and their defaults:
#   RESOURCE_GROUP=pras-rg
#   LOCATION=westeurope
#   ACR_NAME=prasacr<RANDOM>      # must be globally unique; set explicitly
#                                   to reuse the same registry across runs.
#   ENVIRONMENT=pras-env
#   APP_NAME=pras-api
#   IMAGE_TAG=latest
#
# What this does (idempotent — safe to re-run after code edits):
#   1. Creates resource group, ACR registry, and Container Apps environment
#      if they do not already exist.
#   2. Builds the Docker image inside ACR (no local Docker daemon needed).
#   3. Creates or updates the pras-api Container App with the new image.
#   4. Prints the public HTTPS URL of the deployed app.
#
# Tear down with: ./scripts/azure_destroy.sh

set -euo pipefail

# -- Settings (override via env) -------------------------------------------
RESOURCE_GROUP="${RESOURCE_GROUP:-pras-rg}"
LOCATION="${LOCATION:-francecentral}"
ACR_NAME="${ACR_NAME:-prasacr$RANDOM}"
ENVIRONMENT="${ENVIRONMENT:-pras-env}"
LOG_LEVEL="${LOG_LEVEL:-INFO}"
APP_NAME="${APP_NAME:-pras-api}"
IMAGE_TAG="${IMAGE_TAG:-latest}"
IMAGE_NAME="pras-api:${IMAGE_TAG}"

# -- Pre-flight ------------------------------------------------------------
if ! command -v az >/dev/null 2>&1; then
  echo "ERROR: 'az' CLI not found. Install it with: brew install azure-cli" >&2
  exit 1
fi

if ! az account show >/dev/null 2>&1; then
  echo "ERROR: not logged in. Run 'az login' first." >&2
  exit 1
fi

if [[ -z "${OPENAI_API_KEY:-}" ]]; then
  echo "WARNING: OPENAI_API_KEY is not set — deploying without LLM credentials." >&2
  echo "         The /api/analyze endpoint will still work with mock data." >&2
fi

echo "==> Subscription: $(az account show --query name -o tsv)"
echo "==> Resource group: ${RESOURCE_GROUP} (${LOCATION})"
echo "==> ACR:            ${ACR_NAME}"
echo "==> Environment:    ${ENVIRONMENT}"
echo "==> App:            ${APP_NAME}"
echo

# -- Step 1: Resource Group -----------------------------------------------
echo "==> Ensuring resource group exists..."
az group create \
  --name "${RESOURCE_GROUP}" \
  --location "${LOCATION}" \
  --output none

# -- Step 2: Container Registry -------------------------------------------
echo "==> Ensuring Azure Container Registry exists..."
if ! az acr show --name "${ACR_NAME}" --resource-group "${RESOURCE_GROUP}" >/dev/null 2>&1; then
  az acr create \
    --resource-group "${RESOURCE_GROUP}" \
    --name "${ACR_NAME}" \
    --sku Basic \
    --admin-enabled true \
    --output none
fi
ACR_LOGIN_SERVER="$(az acr show --name "${ACR_NAME}" --query loginServer -o tsv)"

# -- Step 3: Build image in ACR -------------------------------------------
echo "==> Building image '${IMAGE_NAME}' in ACR (this can take 2–4 minutes)..."
az acr build \
  --registry "${ACR_NAME}" \
  --image "${IMAGE_NAME}" \
  --file Dockerfile \
  . \
  --output none

# -- Step 4: Container Apps Environment -----------------------------------
echo "==> Ensuring Container Apps environment exists..."
if ! az containerapp env show --name "${ENVIRONMENT}" --resource-group "${RESOURCE_GROUP}" >/dev/null 2>&1; then
  az containerapp env create \
    --name "${ENVIRONMENT}" \
    --resource-group "${RESOURCE_GROUP}" \
    --location "${LOCATION}" \
    --output none
fi

# -- Step 5: Deploy / update Container App --------------------------------
ACR_USERNAME="$(az acr credential show --name "${ACR_NAME}" --query username -o tsv)"
ACR_PASSWORD="$(az acr credential show --name "${ACR_NAME}" --query passwords[0].value -o tsv)"

ENV_VARS=(
  "APP_ENV=production"
  "LOG_LEVEL=${LOG_LEVEL:-INFO}"
)
if [[ -n "${OPENAI_API_KEY:-}" ]]; then
  ENV_VARS+=("OPENAI_API_KEY=${OPENAI_API_KEY}")
fi

if az containerapp show --name "${APP_NAME}" --resource-group "${RESOURCE_GROUP}" >/dev/null 2>&1; then
  echo "==> Updating existing Container App with new image..."
  az containerapp update \
    --name "${APP_NAME}" \
    --resource-group "${RESOURCE_GROUP}" \
    --image "${ACR_LOGIN_SERVER}/${IMAGE_NAME}" \
    --set-env-vars "${ENV_VARS[@]}" \
    --output none
else
  echo "==> Creating new Container App..."
  az containerapp create \
    --name "${APP_NAME}" \
    --resource-group "${RESOURCE_GROUP}" \
    --environment "${ENVIRONMENT}" \
    --image "${ACR_LOGIN_SERVER}/${IMAGE_NAME}" \
    --target-port 8000 \
    --ingress external \
    --registry-server "${ACR_LOGIN_SERVER}" \
    --registry-username "${ACR_USERNAME}" \
    --registry-password "${ACR_PASSWORD}" \
    --env-vars "${ENV_VARS[@]}" \
    --cpu 0.5 \
    --memory 1.0Gi \
    --min-replicas 0 \
    --max-replicas 2 \
    --output none
fi

# -- Done ------------------------------------------------------------------
APP_FQDN="$(az containerapp show \
  --name "${APP_NAME}" \
  --resource-group "${RESOURCE_GROUP}" \
  --query properties.configuration.ingress.fqdn -o tsv)"

echo
echo "==> Deployment complete."
echo "    Public URL:  https://${APP_FQDN}"
echo "    Health:      https://${APP_FQDN}/health"
echo "    UI:          https://${APP_FQDN}/"
echo
echo "Tear down with: ./scripts/azure_destroy.sh"
