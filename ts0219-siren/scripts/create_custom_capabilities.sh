#!/usr/bin/env bash
set -euo pipefail

# Creates/updates the custom capabilities and their capability presentations.
#
# The driver intentionally uses the namespace below:
#   oceancircle09600
#
# SmartThings creates custom capabilities under the namespace of the selected
# CLI organization. If your CLI default organization is not the organization
# that owns oceancircle09600, set SMARTTHINGS_ORGANIZATION_ID before running:
#
#   smartthings organizations
#   SMARTTHINGS_ORGANIZATION_ID=<organization-id-for-oceancircle09600> ./scripts/create_custom_capabilities.sh
#
# Or configure your SmartThings CLI profile so that this organization is the
# default organization.

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
NS="${SMARTTHINGS_NAMESPACE:-oceancircle09600}"
ORG_ID="${SMARTTHINGS_ORGANIZATION_ID:-}"

if [[ "$NS" != "oceancircle09600" ]]; then
  echo "ERROR: This package is built for namespace oceancircle09600, but SMARTTHINGS_NAMESPACE=$NS" >&2
  echo "Unset SMARTTHINGS_NAMESPACE or rebuild the driver/profile/Lua files for a different namespace." >&2
  exit 1
fi

ORG_ARGS=()
if [[ -n "$ORG_ID" ]]; then
  ORG_ARGS=(-O "$ORG_ID")
  echo "Using SmartThings organization: $ORG_ID"
else
  echo "No SMARTTHINGS_ORGANIZATION_ID set; using the SmartThings CLI default organization."
  echo "If capabilities are created as another namespace, rerun with:"
  echo "  SMARTTHINGS_ORGANIZATION_ID=<organization-id-for-oceancircle09600> $0"
fi

run_st() {
  local tmp
  tmp="$(mktemp)"
  set +e
  "$@" > >(tee "$tmp") 2> >(tee -a "$tmp" >&2)
  local rc=$?
  set -e

  if [[ $rc -eq 0 ]]; then
    rm -f "$tmp"
    return 0
  fi

  # Allow reruns when the object already exists, but do not hide permission,
  # validation, or namespace errors.
  if grep -Eiq 'already exists|ConflictError' "$tmp"; then
    echo "Already exists; continuing."
    rm -f "$tmp"
    return 0
  fi

  echo "ERROR: command failed: $*" >&2
  rm -f "$tmp"
  exit "$rc"
}

for file in "$ROOT"/custom-capabilities/capabilities/*.json; do
  echo "Creating capability from ${file}"
  run_st smartthings capabilities:create -i "${file}" "${ORG_ARGS[@]}"
done

for file in "$ROOT"/custom-capabilities/presentations/*.json; do
  base="$(basename "${file}" .json)"
  echo "Creating presentation ${NS}.${base} from ${file}"
  run_st smartthings capabilities:presentation:create "${NS}.${base}" 1 -i "${file}" "${ORG_ARGS[@]}"
done

echo "Done. Now package the driver with: smartthings edge:drivers:package $ROOT"
