#!/usr/bin/env sh
# Read-only diagnostics. NEVER prints control tokens, authentication headers,
# or SmartThings preference values. Suitable for bug reports after IP review.
set -u
PORT=8765
IFACE=''
while [ "$#" -gt 0 ]; do
  case "$1" in
    --interface) [ "$#" -ge 2 ] || exit 2; IFACE=$2; shift 2 ;;
    --port) [ "$#" -ge 2 ] || exit 2; PORT=$2; shift 2 ;;
    *) echo "Usage: $0 [--interface IFACE] [--port PORT]" >&2; exit 2 ;;
  esac
done
case "$PORT" in ''|*[!0-9]*) echo 'Invalid port.' >&2; exit 2 ;; esac
printf 'Linux Host diagnostics (read-only)\n'
printf 'Kernel: '; uname -sr
printf 'Init: '; if command -v systemctl >/dev/null 2>&1; then systemctl --version | head -n 1; else echo 'no systemctl'; fi
if command -v systemctl >/dev/null 2>&1; then
  for unit in linux-host-agent.service linux-host-agent-power.socket avahi-daemon.service NetworkManager.service systemd-networkd.service; do
    printf '%s: ' "$unit"
    systemctl is-active "$unit" 2>/dev/null || true
  done
fi
printf 'Agent /v1/info (selected non-secret properties):\n'
if command -v python3 >/dev/null 2>&1; then
  python3 - "$PORT" <<'PY'
import json, sys, urllib.request
try:
    with urllib.request.urlopen('http://127.0.0.1:%d/v1/info' % int(sys.argv[1]), timeout=3) as result:
        info=json.load(result)
    for k in ('protocol','api_version','agent_version','hostname','os','wol_interface'):
        print('  %s: %s' % (k,info.get(k)))
    # No stable installation UUID, secret or IP address in public diagnostics.
    print('  WOL MAC present:',bool(info.get('wol_mac')))
    print('  WOL broadcast present:',bool(info.get('wol_broadcast')))
    print('  Power-control enabled:', 'power-control' in info.get('features',[]))
except (OSError, ValueError, KeyError) as e:
    print('  Agent unavailable:',str(e))
PY
fi
if [ -n "$IFACE" ]; then
  case "$IFACE" in *[!a-zA-Z0-9_.-]*|'') exit 2 ;; esac
  [ "${#IFACE}" -le 15 ] || exit 2
  printf 'WOL support/current state for %s:\n' "$IFACE"
  if ! command -v ethtool >/dev/null 2>&1; then
    echo '  unavailable: ethtool is not installed'
  elif [ ! -e "/sys/class/net/$IFACE/address" ]; then
    echo '  unavailable: interface does not exist'
  else
    # WOL_GET via netlink may require CAP_NET_ADMIN. A partially successful
    # ethtool invocation is not usable; check for both lines, then use ioctl.
    WOL_INFO=''
    if WOL_INFO=$(ethtool "$IFACE" 2>/dev/null) &&
       printf '%s\n' "$WOL_INFO" | grep -Eq '^[[:space:]]*Supports Wake-on:' &&
       printf '%s\n' "$WOL_INFO" | grep -Eq '^[[:space:]]*Wake-on:'; then
      printf '%s\n' "$WOL_INFO" | grep -i 'Wake-on'
    elif WOL_INFO=$(ethtool --disable-netlink "$IFACE" 2>/dev/null) &&
         printf '%s\n' "$WOL_INFO" | grep -Eq '^[[:space:]]*Supports Wake-on:' &&
         printf '%s\n' "$WOL_INFO" | grep -Eq '^[[:space:]]*Wake-on:'; then
      printf '  %s\n' 'Legacy ioctl fallback used (netlink unavailable to current user)'
      printf '%s\n' "$WOL_INFO" | grep -i 'Wake-on'
    else
      echo '  unavailable: ethtool query failed or returned no WOL data'
      printf '  Try: sudo ethtool %s\n' "$IFACE"
      printf '  Or:  ethtool --disable-netlink %s\n' "$IFACE"
      echo '  This does not mean that WOL is unsupported.'
    fi
  fi
fi
echo 'Never attach /var/lib/linux-host-agent/control-token or raw authenticated HTTP requests.'
