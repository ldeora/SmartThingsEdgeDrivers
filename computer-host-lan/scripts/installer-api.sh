#!/usr/bin/env sh
# JSON-only, unprivileged entry point for the experimental installer API.
# Use the same interpreter selector as preflight.sh/install-agent.sh so a
# distribution's default python3 can be <3.10 when a newer one is available.
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
. "$ROOT/scripts/python-selector.sh"
OVERRIDE=''
override_supplied=0
operation=unknown
case "${1-}" in
  inspect|plan) operation=$1 ;;
esac

# Match argparse's two accepted spellings. Never interpolate input into shell
# code or print it in errors. Detect an omitted value even without Python.
expect_python=0
for arg in "$@"; do
  if [ "$expect_python" -eq 1 ]; then
    case "$arg" in
      --*) break ;;
    esac
    OVERRIDE=$arg
    expect_python=0
    break
  fi
  case "$arg" in
    --python) override_supplied=1; expect_python=1 ;;
    --python=*) override_supplied=1; OVERRIDE=${arg#--python=}; break ;;
  esac
done

if [ "$expect_python" -eq 1 ] || { [ "$override_supplied" -eq 1 ] && [ -z "$OVERRIDE" ]; }; then
  error_code=invalid_argument
elif linuxhost_select_python "$OVERRIDE" 2>/dev/null; then
  exec "$LINUXHOST_PYTHON" "$ROOT/scripts/installer_api.py" "$@"
else
  if [ "$override_supplied" -eq 1 ]; then
    error_code=invalid_argument
  else
    error_code=prerequisite_missing
  fi
fi

# Same key order, compact separators and trailing newline as error_response().
# All fields come from closed, internal allowlists; user input is never echoed.
printf '{"error":{"code":"%s"},"mode":"read_only","operation":"%s","schema_version":1}\n' "$error_code" "$operation" >&2
exit 2
