#!/usr/bin/env sh
# Explicit opt-in WOL setup for systemd Linux with NetworkManager or udev .link.
# Dry-run by default. Never restarts networking or changes interfaces on its own.
set -eu
IFACE=''
APPLY=0
usage() { echo "Usage: $0 --interface IFNAME [--apply]" >&2; exit 2; }
while [ "$#" -gt 0 ]; do
  case "$1" in
    --interface) [ "$#" -ge 2 ] || usage; IFACE=$2; shift 2 ;;
    --apply) APPLY=1; shift ;;
    *) usage ;;
  esac
done
[ -n "$IFACE" ] || usage
case "$IFACE" in *[!a-zA-Z0-9_.-]*|'') usage;; esac
[ "${#IFACE}" -le 15 ] || usage
if [ "$APPLY" -eq 1 ] && [ "$(id -u)" -ne 0 ]; then
  echo 'Run --apply as root. Dry runs do not require root.' >&2
  exit 1
fi
[ -e "/sys/class/net/$IFACE/address" ] || { echo "No such interface: $IFACE" >&2; exit 1; }
command -v ethtool >/dev/null 2>&1 || { echo 'ethtool is required for WOL checks.' >&2; exit 1; }
# A netlink WOL_GET can require CAP_NET_ADMIN even for a read-only query.
# Some ethtool versions print a netlink permission error yet return success
# with incomplete output. Require BOTH WOL lines, then try legacy ioctl.
query_wol() {
  WOL_INFO=''
  WOL_BACKEND=''
  if WOL_INFO=$(ethtool "$IFACE" 2>/dev/null) &&
     printf '%s\n' "$WOL_INFO" | grep -Eq '^[[:space:]]*Supports Wake-on:' &&
     printf '%s\n' "$WOL_INFO" | grep -Eq '^[[:space:]]*Wake-on:'; then
    WOL_BACKEND='ethtool (netlink/default)'
    return 0
  fi
  if WOL_INFO=$(ethtool --disable-netlink "$IFACE" 2>/dev/null) &&
     printf '%s\n' "$WOL_INFO" | grep -Eq '^[[:space:]]*Supports Wake-on:' &&
     printf '%s\n' "$WOL_INFO" | grep -Eq '^[[:space:]]*Wake-on:'; then
    WOL_BACKEND='ethtool --disable-netlink (ioctl)'
    return 0
  fi
  return 1
}
if ! query_wol; then
  echo "Cannot reliably read WOL capabilities for $IFACE (not proof that WOL is unsupported)." >&2
  echo "Try: sudo ethtool $IFACE" >&2
  echo "Or:  ethtool --disable-netlink $IFACE" >&2
  exit 1
fi
printf '%s\n' "$WOL_INFO" | grep -Eq '^[[:space:]]*Supports Wake-on:.*g' || {
  echo "Interface $IFACE does not advertise magic-packet WOL support." >&2; exit 1;
}
printf 'WOL query method: %s\n' "$WOL_BACKEND"
MAC=$(cat "/sys/class/net/$IFACE/address")
case "$MAC" in
  ??:??:??:??:??:??) ;;
  *) echo 'Cannot determine Ethernet MAC.' >&2; exit 1 ;;
esac
printf 'Interface: %s (%s)\n' "$IFACE" "$MAC"
if systemctl is-active --quiet NetworkManager.service 2>/dev/null; then
  command -v nmcli >/dev/null 2>&1 || { echo 'NetworkManager active, nmcli not found.' >&2; exit 1; }
  UUID=$(nmcli -g GENERAL.CON-UUID device show "$IFACE" 2>/dev/null || true)
  case "$UUID" in ''|'--') echo "No active NetworkManager connection for $IFACE." >&2; exit 1;; esac
  echo "NetworkManager: will set 802-3-ethernet.wake-on-lan=magic for connection $UUID"
  if [ "$APPLY" -eq 1 ]; then
    [ "$(id -u)" -eq 0 ] || { echo 'Run --apply as root.' >&2; exit 1; }
    nmcli connection modify "$UUID" 802-3-ethernet.wake-on-lan magic
  fi
else
  command -v udevadm >/dev/null 2>&1 || { echo 'systemd-udev is needed for persistent .link configuration.' >&2; exit 1; }
  MAC_COMPACT=$(printf '%s' "$MAC" | tr -d ':' | tr 'ABCDEF' 'abcdef')
  LINK_DIR=/etc/systemd/network
  LINK_FILE="$LINK_DIR/10-linux-host-wol-$MAC_COMPACT.link"
  # A per-MAC .link file is appropriate for systemd-networkd and other
  # systemd-udev based setups. It does not configure IP or routing.
  # Respect a per-NIC configuration already installed by an operator.
  # In particular, do not replace examplehost's working 10-wol.link configuration.
  ALREADY=''
  for existing in "$LINK_DIR"/*.link; do
    [ -f "$existing" ] || continue
    if grep -Fxq "MACAddress=$MAC" "$existing" && grep -Fxq 'WakeOnLan=magic' "$existing"; then
      ALREADY=$existing
      break
    fi
  done
  if [ -n "$ALREADY" ]; then
    echo "Found an existing per-MAC persistent WOL rule: $ALREADY"
  elif [ -e "$LINK_FILE" ]; then
    if ! grep -Fxq "MACAddress=$MAC" "$LINK_FILE" || ! grep -Fxq 'WakeOnLan=magic' "$LINK_FILE"; then
      echo "Refusing to overwrite an existing different $LINK_FILE" >&2
      exit 1
    fi
    echo "Existing WOL .link configuration: $LINK_FILE"
  else
    echo "Will create $LINK_FILE with [Match] MACAddress and [Link] WakeOnLan=magic."
    if [ "$APPLY" -eq 1 ]; then
      [ "$(id -u)" -eq 0 ] || { echo 'Run --apply as root.' >&2; exit 1; }
      install -d -m 0755 "$LINK_DIR"
      TMP=$(mktemp "$LINK_DIR/.linux-host-wol.XXXXXXXX")
      trap 'rm -f "$TMP"' EXIT HUP INT TERM
      printf '[Match]\nMACAddress=%s\n\n[Link]\nNamePolicy=keep kernel database onboard slot path\nWakeOnLan=magic\n' "$MAC" > "$TMP"
      chmod 0644 "$TMP"
      # Never overwrite files on an automated reinstall.
      # Atomic no-clobber creation: never overwrite a concurrent file.
      ln "$TMP" "$LINK_FILE"
      rm -f "$TMP"
      trap - EXIT HUP INT TERM
    fi
  fi
  echo 'NOTE: systemd-udev applies the first matching .link file in lexical order.'
  echo 'Verify with: networkctl status IFACE / udevadm test-builtin net_setup_link ...'
fi
if [ "$APPLY" -eq 1 ]; then
  # Immediate runtime enablement; persistent configuration takes effect
  # at next boot/link reinitialization. Do not bounce the network here.
  ethtool -s "$IFACE" wol g
  if query_wol; then
    printf '%s\n' "$WOL_INFO" | grep -i 'Wake-on'
  else
    echo 'WOL was set, but verification query failed; verify as root with ethtool.' >&2
    exit 1
  fi
  echo 'Reboot and verify Wake-on: g before trusting remote power-on.'
else
  echo 'Dry run. Use --apply to make persistent and current changes.'
fi
