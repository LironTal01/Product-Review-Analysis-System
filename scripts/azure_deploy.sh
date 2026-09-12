#!/usr/bin/env bash
# Deploy PRAS to Azure Container Apps.
#
# Required before the first run:
#   export ACR_NAME=<globally-unique-lowercase-name>
#   export SCRAPER_API_KEY=<secret>
#   export OPENAI_API_KEY=<secret>        # recommended for the complete AI pipeline
#
# Optional:
#   export REDIS_URL=<managed-redis-url>  # caching is disabled when omitted
#   export ALLOW_MOCK_FALLBACK=true       # permits a demo without live scraping

set -Eeuo pipefail

RESOURCE_GROUP="${RESOURCE_GROUP:-pras-rg}"
LOCATION="${LOCATION:-francecentral}"
ACR_NAME="${ACR_NAME:-}"
ENVIRONMENT="${ENVIRONMENT:-pras-env}"
APP_NAME="${APP_NAME:-pras-api}"
IMAGE_TAG="${IMAGE_TAG:-latest}"
IMAGE_NAME="pras-api:${IMAGE_TAG}"
LOG_LEVEL="${LOG_LEVEL:-INFO}"
OPENAI_LLM_MODEL="${OPENAI_LLM_MODEL:-gpt-5-nano}"
ALLOW_MOCK_FALLBACK="${ALLOW_MOCK_FALLBACK:-false}"

# -- Pre-flight ------------------------------------------------------------
if ! command -v az >/dev/null 2>&1; then
  echo "ERROR: Azure CLI ('az') was not found." >&2
  echo "Install it from https://learn.microsoft.com/cli/azure/install-azure-cli" >&2
  exit 1
fi

if ! az account show >/dev/null 2>&1; then
  echo "ERROR: Not logged in to Azure. Run 'az login' first." >&2
  exit 1
fi

if [[ -z "${ACR_NAME}" ]]; then
  echo "ERROR: ACR_NAME is required and must be globally unique." >&2
  echo "Example: ACR_NAME=prasacrlirontal01 ./scripts/azure_deploy.sh" >&2
  exit 1
fi

if [[ ! "${ACR_NAME}" =~ ^[a-z0-9]{5,50}$ ]]; then
  echo "ERROR: ACR_NAME must contain 5-50 lowercase letters and digits only." >&2
  exit 1
fi

MOCK_FALLBACK_NORMALIZED="$(printf '%s' "${ALLOW_MOCK_FALLBACK}" | tr '[:upper:]' '[:lower:]')"
if [[ -z "${SCRAPER_API_KEY:-}" && "${MOCK_FALLBACK_NORMALIZED}" != "true" ]]; then
  echo "ERROR: SCRAPER_API_KEY is required for live review retrieval." >&2
  echo "For an explicit mock-data demo, set ALLOW_MOCK_FALLBACK=true." >&2
  exit 1
fi

if [[ -z "${OPENAI_API_KEY:-}" ]]; then
  echo "WARNING: OPENAI_API_KEY is not set; semantic selection and LLM analysis" >&2
  echo "         will fall back to deterministic statistics." >&2
fi

if [[ -z "${REDIS_URL:-}" ]]; then
  echo "INFO: REDIS_URL is not set; the deployed app will run without caching." >&2
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
echo "==> Building image '${IMAGE_NAME}' in ACR..."
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

# -- Step 5: Runtime configuration ----------------------------------------
ENV_VARS=(
  "APP_ENV=production"
  "LOG_LEVEL=${LOG_LEVEL}"
  "OPENAI_LLM_MODEL=${OPENAI_LLM_MODEL}"
  "ALLOW_MOCK_FALLBACK=${ALLOW_MOCK_FALLBACK}"
)
SECRETS=()

if [[ -n "${OPENAI_API_KEY:-}" ]]; then
  SECRETS+=("openai-api-key=${OPENAI_API_KEY}")
  ENV_VARS+=("OPENAI_API_KEY=secretref:openai-api-key")
fi
if [[ -n "${SCRAPER_API_KEY:-}" ]]; then
  SECRETS+=("scraper-api-key=${SCRAPER_API_KEY}")
  ENV_VARS+=("SCRAPER_API_KEY=secretref:scraper-api-key")
fi
if [[ -n "${REDIS_URL:-}" ]]; then
  SECRETS+=("redis-url=${REDIS_URL}")
  ENV_VARS+=("REDIS_URL=secretref:redis-url")
fi

ACR_USERNAME="$(az acr credential show --name "${ACR_NAME}" --query username -o tsv)"
ACR_PASSWORD="$(az acr credential show --name "${ACR_NAME}" --query passwords[0].value -o tsv)"

# -- Step 6: Deploy or update Container App -------------------------------
if az containerapp show --name "${APP_NAME}" --resource-group "${RESOURCE_GROUP}" >/dev/null 2>&1; then
  echo "==> Updating existing Container App..."
  if ((${#SECRETS[@]})); then
    az containerapp secret set \
      --name "${APP_NAME}" \
      --resource-group "${RESOURCE_GROUP}" \
      --secrets "${SECRETS[@]}" \
      --output none
  fi
  az containerapp update \
    --name "${APP_NAME}" \
    --resource-group "${RESOURCE_GROUP}" \
    --image "${ACR_LOGIN_SERVER}/${IMAGE_NAME}" \
    --set-env-vars "${ENV_VARS[@]}" \
    --output none
else
  echo "==> Creating new Container App..."
  CREATE_ARGS=(
    az containerapp create
    --name "${APP_NAME}"
    --resource-group "${RESOURCE_GROUP}"
    --environment "${ENVIRONMENT}"
    --image "${ACR_LOGIN_SERVER}/${IMAGE_NAME}"
    --target-port 8000
    --ingress external
    --registry-server "${ACR_LOGIN_SERVER}"
    --registry-username "${ACR_USERNAME}"
    --registry-password "${ACR_PASSWORD}"
    --env-vars "${ENV_VARS[@]}"
    --cpu 0.5
    --memory 1.0Gi
    --min-replicas 0
    --max-replicas 2
    --output none
  )
  if ((${#SECRETS[@]})); then
    CREATE_ARGS+=(--secrets "${SECRETS[@]}")
  fi
  "${CREATE_ARGS[@]}"
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
