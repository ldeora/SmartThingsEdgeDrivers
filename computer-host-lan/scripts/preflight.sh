#!/usr/bin/env sh
# Read-only environmental compatibility check. Does NOT require root privileges.
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
. "$ROOT/scripts/python-selector.sh"
INTERFACE=''
PYTHON_OVERRIDE=''
usage() { echo 'Usage: ./scripts/preflight.sh [--interface IFNAME] [--python /absolute/path]' >&2; exit 2; }
while [ "$#" -gt 0 ]; do
  case "$1" in
    --interface) [ "$#" -ge 2 ] || usage; INTERFACE=$2; shift 2 ;;
    --python) [ "$#" -ge 2 ] || usage; PYTHON_OVERRIDE=$2; shift 2 ;;
    *) usage ;;
  esac
done
if [ -n "$INTERFACE" ]; then
  case "$INTERFACE" in *[!a-zA-Z0-9_.-]*|'') usage;; esac
  [ "${#INTERFACE}" -le 15 ] || usage
fi
[ -r /etc/os-release ] && os_name=$(sed -n 's/^PRETTY_NAME=//p' /etc/os-release | head -n 1 | tr -d '"') || os_name='Unknown Linux distribution'
echo 'Linux Host Agent preflight (read-only)'
printf 'Distribution: %s\n' "$os_name"
printf 'Architecture: %s\n' "$(uname -m)"
printf 'Kernel: %s\n' "$(uname -r)"
fail=0
if [ -d /run/systemd/system ]; then
  echo '[OK] systemd is active'
else
  echo '[FAIL] systemd is not the active init; current installer only supports systemd'
  fail=1
fi
for tool in systemctl useradd getent install sed; do
  if command -v "$tool" >/dev/null 2>&1; then
    printf '[OK] %s available\n' "$tool"
  else
    printf '[FAIL] %s is missing\n' "$tool"
    fail=1
  fi
done
if linuxhost_select_python "$PYTHON_OVERRIDE"; then
  printf '[OK] Interpreter: %s (%s)\n' "$LINUXHOST_PYTHON" "$("$LINUXHOST_PYTHON" --version 2>&1)"
else
  echo '[FAIL] No compatible Python 3.10+ interpreter found'
  fail=1
fi
if command -v systemctl >/dev/null 2>&1; then
  for name in NetworkManager.service systemd-networkd.service avahi-daemon.service; do
    state=$(systemctl is-active "$name" 2>/dev/null || true)
    printf '[INFO] %s: %s\n' "$name" "${state:-unavailable}"
  done
fi
if command -v getenforce >/dev/null 2>&1; then
  printf '[INFO] SELinux: %s\n' "$(getenforce 2>/dev/null || echo unknown)"
else
  echo '[INFO] SELinux utilities: not installed (not proof SELinux is disabled)'
fi
if command -v aa-status >/dev/null 2>&1; then
  if aa-status --enabled >/dev/null 2>&1; then
    echo '[INFO] AppArmor: enabled (policy compatibility not yet validated)'
  else
    echo '[INFO] AppArmor: no enabled policy reported'
  fi
fi
for tool in ethtool udevadm nmcli; do
  if command -v "$tool" >/dev/null 2>&1; then
    printf '[INFO] Optional %s: installed\n' "$tool"
  else
    printf '[INFO] Optional %s: missing\n' "$tool"
  fi
done
if [ -n "$INTERFACE" ]; then
  if [ -e "/sys/class/net/$INTERFACE/address" ]; then
    printf '[OK] Selected interface %s exists\n' "$INTERFACE"
  else
    printf '[FAIL] Selected interface %s does not exist\n' "$INTERFACE"
    fail=1
  fi
fi
echo 'Note: TCP/8765 and UDP/5353 require LAN firewall review; no firewall settings were changed.'
echo 'Note: WOL and CPU temperature require hardware support; check them separately.'
if [ "$fail" -ne 0 ]; then
  echo 'Preflight: incompatible or incomplete host; installation should not proceed.'
  exit 1
fi
echo 'Preflight: core requirements present; this is NOT a distribution certification.'
