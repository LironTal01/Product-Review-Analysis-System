#!/usr/bin/env bash
# Tear down all Azure resources created by ./scripts/azure_deploy.sh
# so the project stops incurring charges.
#
# Usage:
#   ./scripts/azure_destroy.sh                  # uses default RESOURCE_GROUP
#   RESOURCE_GROUP=my-rg ./scripts/azure_destroy.sh
#
# This deletes the *entire* resource group, which removes the registry,
# Container Apps environment, app, and any other resources inside it.

set -euo pipefail

RESOURCE_GROUP="${RESOURCE_GROUP:-pras-rg}"

if ! command -v az >/dev/null 2>&1; then
  echo "ERROR: 'az' CLI not found." >&2
  exit 1
fi

if ! az account show >/dev/null 2>&1; then
  echo "ERROR: not logged in. Run 'az login' first." >&2
  exit 1
fi

if ! az group show --name "${RESOURCE_GROUP}" >/dev/null 2>&1; then
  echo "Resource group '${RESOURCE_GROUP}' does not exist — nothing to do."
  exit 0
fi

echo "About to delete resource group: ${RESOURCE_GROUP}"
echo "Subscription: $(az account show --query name -o tsv)"
read -r -p "Type the resource group name to confirm: " confirm

if [[ "${confirm}" != "${RESOURCE_GROUP}" ]]; then
  echo "Aborted — confirmation did not match."
  exit 1
fi

echo "==> Deleting resource group (this runs in the background on Azure)..."
az group delete \
  --name "${RESOURCE_GROUP}" \
  --yes \
  --no-wait

echo "==> Delete request accepted. Resources will be removed shortly."
