#!/usr/bin/env sh
# Minimal privacy-conscious beta report for sharing with maintainers.
# Intentionally excludes hostnames, IPv4/IPv6 addresses, MACs, UUIDs,
# authentication tokens, network paths, device IDs, raw journal records.
set -eu
PORT=8765
while [ "$#" -gt 0 ]; do
  case "$1" in
    --port) [ "$#" -ge 2 ] || { echo 'Missing --port value.' >&2; exit 2; }; PORT=$2; shift 2 ;;
    *) echo "Usage: $0 [--port PORT]" >&2; exit 2 ;;
  esac
done
case "$PORT" in ''|*[!0-9]*) echo 'Invalid TCP port.' >&2; exit 2 ;; esac
[ "${#PORT}" -le 5 ] && [ "$PORT" -ge 1 ] && [ "$PORT" -le 65535 ] || {
  echo 'Invalid TCP port (1-65535).' >&2
  exit 2
}
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
. "$ROOT/scripts/python-selector.sh"
linuxhost_select_python '' >/dev/null || { echo 'ERROR: Python >=3.10 required' >&2; exit 1; }
"$LINUXHOST_PYTHON" - "$PORT" <<'PY'
import os
import platform
import subprocess
import sys
import urllib.error
import urllib.request
import json


def service(name):
    try:
        p = subprocess.run(['systemctl', 'is-active', name], stdout=subprocess.PIPE,
                           stderr=subprocess.DEVNULL, text=True, timeout=3)
        return p.stdout.strip() if p.stdout.strip() in ('active', 'inactive', 'failed', 'activating', 'deactivating') else 'unknown'
    except (OSError, subprocess.TimeoutExpired):
        return 'unavailable'


def label():
    try:
        with open('/etc/os-release', encoding='utf8') as f:
            pairs = dict(line.strip().split('=', 1) for line in f if '=' in line)
        return pairs.get('PRETTY_NAME', 'unknown').strip('"').replace('\n', ' ')[:100]
    except OSError:
        return 'unknown'


print('Computer Host LAN beta report (redacted; no secrets or network identifiers)')
print('Distribution:', label())
print('Architecture:', platform.machine())
print('Kernel:', platform.release())
print('Python:', '.'.join(map(str, sys.version_info[:3])))
for name in ('linux-host-agent.service', 'linux-host-agent-power.socket',
             'avahi-daemon.service', 'NetworkManager.service', 'systemd-networkd.service'):
    print(f'{name}:', service(name))
try:
    with urllib.request.urlopen(f'http://127.0.0.1:{int(sys.argv[1])}/v2/info', timeout=2) as r:
        payload = json.load(r)
    if payload.get('protocol') != 'computer-host-agent':
        print('Agent API: unexpected protocol')
    else:
        version = str(payload.get('agent_version', 'unknown'))
        # Allow stable, beta and RC identifiers, but never echo arbitrary agent text.
        import re
        if not re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+(?:-(?:beta|rc)\.[0-9]+)?', version):
            version = 'unknown'
        print('Agent API: responding')
        print('Agent version:', version)
        print('Power control enabled:', 'power-control' in payload.get('features', []))
        print('WOL metadata present:', bool(payload.get('wol_mac')) and bool(payload.get('wol_broadcast')))
except (OSError, ValueError, urllib.error.URLError, json.JSONDecodeError):
    print('Agent API: unavailable')
print('No hostname, IP, MAC, UUID, secret, SmartThings IDs, or raw logs included.')
print('Attach additional logs only after manually redacting personal information.')
PY
