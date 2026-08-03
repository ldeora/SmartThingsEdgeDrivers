#!/usr/bin/env bash
set -euo pipefail

# Creates the SONOFF Hydro custom capabilities and creates/updates their
# capability presentations.
#
# This package intentionally uses the namespace below:
#   oceancircle09600
#
# SmartThings creates custom capabilities under the namespace of the selected
# CLI organization. To avoid accidentally creating capabilities under a random
# default namespace, this script requires SMARTTHINGS_ORGANIZATION_ID unless
# SMARTTHINGS_ALLOW_DEFAULT_ORG=1 is explicitly set.
#
# Recommended:
#   smartthings organizations
#   SMARTTHINGS_ORGANIZATION_ID=<organization-id-for-oceancircle09600> ./scripts/create_custom_capabilities.sh

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
NS="${SMARTTHINGS_NAMESPACE:-oceancircle09600}"
ORG_ID="${SMARTTHINGS_ORGANIZATION_ID:-}"
ALLOW_DEFAULT_ORG="${SMARTTHINGS_ALLOW_DEFAULT_ORG:-0}"

if [[ "$NS" != "oceancircle09600" ]]; then
  echo "ERROR: This package is built for namespace oceancircle09600, but SMARTTHINGS_NAMESPACE=$NS" >&2
  echo "Unset SMARTTHINGS_NAMESPACE or rebuild the profile/Lua/custom capability files for a different namespace." >&2
  exit 1
fi

ORG_ARGS=()
if [[ -n "$ORG_ID" ]]; then
  ORG_ARGS=(-O "$ORG_ID")
  echo "Using SmartThings organization: $ORG_ID"
elif [[ "$ALLOW_DEFAULT_ORG" == "1" ]]; then
  echo "WARNING: SMARTTHINGS_ORGANIZATION_ID is not set; using the CLI default organization because SMARTTHINGS_ALLOW_DEFAULT_ORG=1."
  echo "The script will verify created capability IDs and stop if the namespace is not $NS."
else
  echo "ERROR: SMARTTHINGS_ORGANIZATION_ID is not set." >&2
  echo "Run:" >&2
  echo "  smartthings organizations" >&2
  echo "  SMARTTHINGS_ORGANIZATION_ID=<organization-id-for-$NS> $0" >&2
  echo "If you intentionally want to use the CLI default organization, rerun with SMARTTHINGS_ALLOW_DEFAULT_ORG=1." >&2
  exit 1
fi

RUN_ST_TMP=""
run_st_capture() {
  local tmp rc
  tmp="$(mktemp)"
  RUN_ST_TMP="$tmp"
  set +e
  "$@" > >(tee "$tmp") 2> >(tee -a "$tmp" >&2)
  rc=$?
  set -e
  return "$rc"
}

cleanup_tmp() {
  if [[ -n "${RUN_ST_TMP:-}" && -f "$RUN_ST_TMP" ]]; then
    rm -f "$RUN_ST_TMP"
  fi
  RUN_ST_TMP=""
}

output_has() {
  local pattern="$1"
  [[ -n "${RUN_ST_TMP:-}" && -f "$RUN_ST_TMP" ]] && grep -Eiq "$pattern" "$RUN_ST_TMP"
}

assert_output_namespace() {
  local tmp="$1"
  local expected_id="$2"
  [[ -f "$tmp" ]] || return 0

  # The create APIs usually print a JSON response containing an id. If they do,
  # make sure it is exactly the namespace-qualified ID this package uses.
  local actual_id
  actual_id="$(python3 - "$tmp" <<'PY' || true
import json, re, sys
text=open(sys.argv[1]).read()
try:
    obj=json.loads(text)
    print(obj.get('id',''))
except Exception:
    m=re.search(r'"id"\s*:\s*"([^"]+)"', text)
    print(m.group(1) if m else '')
PY
)"
  if [[ -n "$actual_id" && "$actual_id" != "$expected_id" ]]; then
    echo "ERROR: SmartThings created/returned $actual_id, but this driver expects $expected_id." >&2
    echo "This means the selected CLI organization does not own namespace $NS." >&2
    echo "Rerun with SMARTTHINGS_ORGANIZATION_ID=<organization-id-for-$NS>." >&2
    cleanup_tmp
    exit 1
  fi
}

cap_dir="$ROOT/custom-capabilities/capabilities"
pres_dir="$ROOT/custom-capabilities/presentations"

if [[ ! -d "$cap_dir" || ! -d "$pres_dir" ]]; then
  echo "ERROR: custom-capabilities/capabilities or custom-capabilities/presentations not found." >&2
  exit 1
fi

for file in "$cap_dir"/*.json; do
  base="$(basename "$file" .json)"
  expected_id="$NS.$base"
  echo "Creating capability $expected_id from ${file}"
  if run_st_capture smartthings capabilities:create -i "${file}" "${ORG_ARGS[@]}"; then
    assert_output_namespace "$RUN_ST_TMP" "$expected_id"
    cleanup_tmp
  else
    rc=$?
    if output_has 'already exists|ConflictError|409'; then
      echo "Already exists; continuing."
      cleanup_tmp
    else
      echo "ERROR: command failed: smartthings capabilities:create -i ${file}" >&2
      cleanup_tmp
      exit "$rc"
    fi
  fi
done

for file in "$pres_dir"/*.json; do
  cap_id="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["id"])' "$file")"
  if [[ "$cap_id" != "$NS."* ]]; then
    echo "ERROR: Presentation ${file} has unexpected id ${cap_id}; expected namespace $NS." >&2
    exit 1
  fi

  # Presentations are safe and useful to update when polishing UI layout. This
  # lets existing testers receive presentation-only changes without deleting or
  # recreating immutable custom capability definitions.
  echo "Updating presentation ${cap_id} from ${file}"
  if run_st_capture smartthings capabilities:presentation:update "${cap_id}" -i "${file}" "${ORG_ARGS[@]}"; then
    assert_output_namespace "$RUN_ST_TMP" "$cap_id"
    cleanup_tmp
    continue
  fi

  rc=$?
  if output_has 'not found|NotFound|404|does not exist'; then
    echo "Presentation does not exist yet; creating ${cap_id}."
    cleanup_tmp
    if run_st_capture smartthings capabilities:presentation:create "${cap_id}" 1 -i "${file}" "${ORG_ARGS[@]}"; then
      assert_output_namespace "$RUN_ST_TMP" "$cap_id"
      cleanup_tmp
    else
      rc=$?
      if output_has 'already exists|ConflictError|409'; then
        echo "Already exists; continuing."
        cleanup_tmp
      else
        echo "ERROR: command failed: smartthings capabilities:presentation:create ${cap_id}" >&2
        cleanup_tmp
        exit "$rc"
      fi
    fi
  else
    echo "ERROR: command failed: smartthings capabilities:presentation:update ${cap_id}" >&2
    cleanup_tmp
    exit "$rc"
  fi
done

echo "Done. Now package the driver with: smartthings edge:drivers:package $ROOT"
