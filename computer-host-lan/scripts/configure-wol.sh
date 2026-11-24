#!/usr/bin/env sh
# Read-only WOL planning for systemd Linux with NetworkManager or udev .link.
# Persistent/runtime modification is deferred; never apply changes here.
set -eu
IFACE=''
APPLY=0
usage() { echo "Usage (read-only): $0 --interface IFNAME" >&2; exit 2; }
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
if [ "$APPLY" -eq 1 ]; then
  echo 'Automated WOL configuration is not supported by the v1.0 installer. Preserve existing network settings; this tool is read-only.' >&2
  exit 2
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
  CONFLICT=''
  # Never shadow an operator's per-MAC network link policy. A first-matching
  # .link file can also control Name, MTU and other unrelated properties.
  for existing in "$LINK_DIR"/*.link /run/systemd/network/*.link /usr/lib/systemd/network/*.link; do
    [ -f "$existing" ] || continue
    if grep -iFxq "MACAddress=$MAC" "$existing"; then
      if grep -Fxq 'WakeOnLan=magic' "$existing"; then
        ALREADY=$existing
      else
        CONFLICT=$existing
      fi
      break
    fi
  done
  if [ -n "$CONFLICT" ]; then
    echo "Refusing to shadow existing link configuration: $CONFLICT" >&2
    echo "Add WakeOnLan=magic to its [Link] section manually, keeping all other settings." >&2
    exit 1
  elif [ -n "$ALREADY" ]; then
    echo "Found an existing per-MAC persistent WOL rule: $ALREADY"
  elif [ -e "$LINK_FILE" ]; then
    if ! grep -Fxq "MACAddress=$MAC" "$LINK_FILE" || ! grep -Fxq 'WakeOnLan=magic' "$LINK_FILE"; then
      echo "Refusing to overwrite an existing different $LINK_FILE" >&2
      exit 1
    fi
    echo "Existing WOL .link configuration: $LINK_FILE"
  else
    echo "Proposed $LINK_FILE with [Match] MACAddress and [Link] WakeOnLan=magic."
  fi
  echo 'NOTE: systemd-udev applies the first matching .link file in lexical order.'
  echo 'Verify with: networkctl status IFACE / udevadm test-builtin net_setup_link ...'
fi
echo 'Dry run. No persistent or current WOL settings changed.'
