#!/usr/bin/env sh
# Restore the exact set of managed files snapshotted before a prior install.
set -eu
[ "$#" -eq 2 ] && [ "$1" = '--backup' ] || { echo "Usage: $0 --backup /var/backups/linux-host-agent/snapshot-..." >&2; exit 2; }
[ "$(id -u)" -eq 0 ] || { echo 'Run as root.' >&2; exit 1; }
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
. "$ROOT/scripts/python-selector.sh"
linuxhost_select_python '' || exit 1
exec "$LINUXHOST_PYTHON" "$ROOT/scripts/install_core.py" --rollback "$2"
