#!/usr/bin/env bash
set -u

CAP_NAMESPACE="${CAP_NAMESPACE:-oceancircle09600}"
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if ! command -v smartthings >/dev/null 2>&1; then
  echo "ERROR: smartthings CLI not found in PATH" >&2
  exit 1
fi

echo "Using SmartThings custom capability namespace: ${CAP_NAMESPACE}"
echo

create_capability_if_needed() {
  local name="$1"
  local file="$2"
  local cap_id="${CAP_NAMESPACE}.${name}"

  echo "Creating ${cap_id} if needed ..."
  if smartthings capabilities:create --namespace="${CAP_NAMESPACE}" -i "${ROOT_DIR}/capabilities/${file}"; then
    echo "Created ${cap_id}"
  else
    echo "Capability create returned non-zero. If ${cap_id} already exists, this is OK; continuing to presentation."
  fi
  echo
}

create_presentation() {
  local name="$1"
  local file="$2"
  local cap_id="${CAP_NAMESPACE}.${name}"

  echo "Creating/updating presentation for ${cap_id} ..."
  if ! smartthings capabilities:presentation:create "${cap_id}" 1 -i "${ROOT_DIR}/presentations/${file}"; then
    echo "ERROR: Presentation creation failed for ${cap_id}" >&2
    exit 1
  fi
  echo
}

create_capability_if_needed "airPurifierDisplayLight" "airPurifierDisplayLight.yaml"
create_presentation "airPurifierDisplayLight" "airPurifierDisplayLight.presentation.yaml"

create_capability_if_needed "airPurifierTimer" "airPurifierTimer.yaml"
create_presentation "airPurifierTimer" "airPurifierTimer.presentation.yaml"

echo "Done. If the capabilities already existed, the create step may have warned; the important part is that presentation creation succeeds."
