#!/usr/bin/env sh
# JSON-only, unprivileged entry point for the experimental installer API.
# Use the same interpreter selector as preflight.sh/install-agent.sh so a
# distribution's default python3 can be <3.10 when a newer one is available.
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
. "$ROOT/scripts/python-selector.sh"
OVERRIDE=''
expect_python=0
for arg in "$@"; do
  if [ "$expect_python" -eq 1 ]; then
    OVERRIDE=$arg
    break
  fi
  [ "$arg" = "--python" ] && expect_python=1
done
if ! linuxhost_select_python "$OVERRIDE" 2>/dev/null; then
  if [ -n "$OVERRIDE" ]; then
    error_code=invalid_argument
  else
    error_code=prerequisite_missing
  fi
  # No raw user input in error output. Never fall back to an old interpreter.
  printf '{"schema_version":1,"operation":"unknown","mode":"read_only","error":{"code":"%s"}}\n' "$error_code" >&2
  exit 2
fi
exec "$LINUXHOST_PYTHON" "$ROOT/scripts/installer_api.py" "$@"
