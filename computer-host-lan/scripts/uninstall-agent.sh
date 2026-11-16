#!/usr/bin/env sh
# Removes managed code/units; retains persistent identity, token and user.
set -eu
[ "$#" -eq 1 ] && [ "$1" = '--confirm' ] || { echo "Usage: sudo $0 --confirm" >&2; exit 2; }
[ "$(id -u)" -eq 0 ] || { echo 'Run as root.' >&2; exit 1; }
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
. "$ROOT/scripts/python-selector.sh"
linuxhost_select_python '' || exit 1
exec "$LINUXHOST_PYTHON" "$ROOT/scripts/install_core.py" --uninstall
