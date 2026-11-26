#!/bin/sh
# Historical restoration is not interrupted-transaction recovery.
set -eu
echo 'Legacy rollback disabled. Use the verified Computer Host LAN installer with -restore, or cli backups followed by cli restore. Preserve your backups. Use -recover only for an interrupted transaction.' >&2
exit 2
