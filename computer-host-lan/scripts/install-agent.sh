#!/usr/bin/env sh
# Legacy source entry point: read-only planning only. Never elevate this script.
set -eu
ENABLE_POWER=0
DISABLE_POWER=0
WOL_INTERFACE=''
CONFIGURE_WOL=0
PYTHON_OVERRIDE=''
DRY_RUN=0
ADOPT_RETAINED_STATE=0
usage() { echo "Usage (read-only): $0 --dry-run [--enable-power|--disable-power] [--wol-interface IFNAME] [--python /absolute/path]" >&2; exit 2; }
while [ "$#" -gt 0 ]; do
  case "$1" in
    --enable-power) ENABLE_POWER=1; shift ;;
    --disable-power) DISABLE_POWER=1; shift ;;
    --configure-wol) CONFIGURE_WOL=1; shift ;;
    --dry-run) DRY_RUN=1; shift ;;
    --adopt-retained-state) ADOPT_RETAINED_STATE=1; shift ;;
    --python) [ "$#" -ge 2 ] || usage; PYTHON_OVERRIDE=$2; shift 2 ;;
    --wol-interface) [ "$#" -ge 2 ] || usage; WOL_INTERFACE=$2; shift 2 ;;
    *) usage ;;
  esac
done
if [ "$DRY_RUN" -ne 1 ]; then
  echo 'Legacy installation disabled. Use the independently verified release installer wizard/CLI as an ordinary user; no source-tree elevation.' >&2
  exit 2
fi
if [ "$CONFIGURE_WOL" -ne 0 ] || [ "$ADOPT_RETAINED_STATE" -ne 0 ]; then
  echo 'Persistent WOL configuration and retained-state adoption are not supported by this installer. Preserve existing state and network configuration.' >&2
  exit 2
fi
[ "$ENABLE_POWER" -eq 0 ] || [ "$DISABLE_POWER" -eq 0 ] || usage
if [ -n "$WOL_INTERFACE" ]; then
  case "$WOL_INTERFACE" in *[!a-zA-Z0-9_.-]*|'') usage;; esac
  [ "${#WOL_INTERFACE}" -le 15 ] && [ -d "/sys/class/net/$WOL_INTERFACE" ] || usage
fi
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
. "$ROOT/scripts/python-selector.sh"
linuxhost_select_python "$PYTHON_OVERRIDE" || exit 1
PYTHON_BIN=$LINUXHOST_PYTHON
# Check source syntax before producing the informational plan.
"$PYTHON_BIN" -c 'import ast,sys,pathlib; [ast.parse(pathlib.Path(p).read_text()) for p in sys.argv[1:]]' \
  "$ROOT/agent/linux_host_agent.py" "$ROOT/agent/power_helper.py" "$ROOT/scripts/install_core.py" || exit 1
# The legacy source plan is informational, not authorization to install.
"$PYTHON_BIN" -B "$ROOT/scripts/install_core.py" --check-existing || exit 1
set -- --plan --source "$ROOT" --python "$PYTHON_BIN"
[ "$ENABLE_POWER" -eq 0 ] || set -- "$@" --enable-power
[ "$DISABLE_POWER" -eq 0 ] || set -- "$@" --disable-power
[ -z "$WOL_INTERFACE" ] || set -- "$@" --wol-interface "$WOL_INTERFACE"
"$PYTHON_BIN" -B "$ROOT/scripts/install_core.py" "$@"
if [ -n "$WOL_INTERFACE" ]; then
  printf 'Proposed WOL interface pin: %s\n' "$WOL_INTERFACE"
  echo 'Persistent WOL not modified.'
fi
echo 'Restrict TCP/8765 to your trusted LAN/hub. No firewall rule was changed.'
echo 'Avahi must be installed and running for mDNS discovery.'
echo 'Control key remains in /var/lib/linux-host-agent/control-token (never post it).'
