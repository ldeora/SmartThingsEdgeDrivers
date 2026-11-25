#!/usr/bin/env sh
# Requires Python >=3.10, PyYAML, Lua 5.4/5.3 shared runtime, and common systemd/shadow tools.
# This script runs safely inside unprivileged/non-systemd CI containers.
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
cd "$ROOT"
export PYTHONDONTWRITEBYTECODE=1
python3 -c 'import sys,yaml; assert sys.version_info >= (3,10); print("Python",sys.version.split()[0], "PyYAML",yaml.__version__)'
python3 -m unittest discover -s tests -q
for file in scripts/*.sh scripts/ci/*.sh; do
    sh -n "$file"
done
./scripts/install-agent.sh --dry-run
# The official test images run as root; additionally verify the agent under
# a dedicated nonroot account when runuser is available.
if [ "$(id -u)" -eq 0 ] && command -v runuser >/dev/null 2>&1 && \
        runuser -u nobody -- test -r scripts/ci/smoke_agent.py; then
    runuser -u nobody -- python3 scripts/ci/smoke_agent.py
else
    if [ "$(id -u)" -eq 0 ]; then
        echo 'NOTE: nonroot source access unavailable here; running loopback smoke as root only.'
    fi
    python3 scripts/ci/smoke_agent.py
fi
printf '%s\n' 'PASS: container-level tests. systemd PID1, MAC policies, Avahi network discovery and power hardware NOT tested.'
