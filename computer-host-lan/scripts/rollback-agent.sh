#!/bin/sh
# Historical restoration is not interrupted-transaction recovery.
set -eu
echo 'Historical backup restoration is not supported by the v1.0 installer. Preserve backups and seek recovery guidance; do not substitute -recover for historical restore.' >&2
exit 2
