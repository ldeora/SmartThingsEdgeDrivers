#!/usr/bin/env sh
# Audited systemd installer. Root required to modify files or services.
# No firewall edits; no network restarts; WOL explicitly opted in.
set -eu
ENABLE_POWER=0
DISABLE_POWER=0
WOL_INTERFACE=''
CONFIGURE_WOL=0
PYTHON_OVERRIDE=''
DRY_RUN=0
ADOPT_RETAINED_STATE=0
usage() { echo "Usage: $0 [--enable-power|--disable-power] [--wol-interface IFNAME] [--configure-wol] [--python /absolute/path] [--dry-run] [--adopt-retained-state]" >&2; exit 2; }
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
[ "$ENABLE_POWER" -eq 0 ] || [ "$DISABLE_POWER" -eq 0 ] || usage
[ "$CONFIGURE_WOL" -eq 0 ] || [ -n "$WOL_INTERFACE" ] || usage
if [ -n "$WOL_INTERFACE" ]; then
  case "$WOL_INTERFACE" in *[!a-zA-Z0-9_.-]*|'') usage;; esac
  [ "${#WOL_INTERFACE}" -le 15 ] && [ -d "/sys/class/net/$WOL_INTERFACE" ] || usage
fi
[ "$DRY_RUN" -eq 1 ] || [ "$(id -u)" -eq 0 ] || { echo 'Run as root.' >&2; exit 1; }
[ "$DRY_RUN" -eq 1 ] || [ -d /run/systemd/system ] || { echo 'Active systemd required; non-systemd init unsupported.' >&2; exit 1; }
for tool in systemctl useradd getent install; do
  command -v "$tool" >/dev/null 2>&1 || { echo "Required command missing: $tool" >&2; exit 1; }
done
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
. "$ROOT/scripts/python-selector.sh"
linuxhost_select_python "$PYTHON_OVERRIDE" || exit 1
PYTHON_BIN=$LINUXHOST_PYTHON
# Preflight ALL sources and Python syntax before creating an account or writing services.
"$PYTHON_BIN" -c 'import ast,sys,pathlib; [ast.parse(pathlib.Path(p).read_text()) for p in sys.argv[1:]]' \
  "$ROOT/agent/linux_host_agent.py" "$ROOT/agent/power_helper.py" "$ROOT/scripts/install_core.py" || exit 1
# Refuse legacy v1 or ambiguous paths before creating linuxhost or touching
# backup/service state. The engine rechecks under its lock before all writes.
if [ "$ADOPT_RETAINED_STATE" -eq 1 ]; then
  "$PYTHON_BIN" "$ROOT/scripts/install_core.py" --check-existing --adopt-retained-state || exit 1
else
  "$PYTHON_BIN" "$ROOT/scripts/install_core.py" --check-existing || exit 1
fi
NOLOGIN_BIN=$(command -v nologin || true)
if [ -z "$NOLOGIN_BIN" ]; then
  for candidate in /usr/sbin/nologin /sbin/nologin /bin/false; do
    [ ! -x "$candidate" ] || { NOLOGIN_BIN=$candidate; break; }
  done
fi
[ -n "$NOLOGIN_BIN" ] || { echo 'No non-login shell available.' >&2; exit 1; }
if [ "$DRY_RUN" -eq 0 ] && ! getent passwd linuxhost >/dev/null 2>&1; then
  useradd --system --user-group --home-dir /var/lib/linux-host-agent \
    --shell "$NOLOGIN_BIN" linuxhost
fi
if [ "$DRY_RUN" -eq 1 ]; then set -- --plan --source "$ROOT" --python "$PYTHON_BIN"; else set -- --install --source "$ROOT" --python "$PYTHON_BIN"; fi
[ "$ENABLE_POWER" -eq 0 ] || set -- "$@" --enable-power
[ "$DISABLE_POWER" -eq 0 ] || set -- "$@" --disable-power
[ -z "$WOL_INTERFACE" ] || set -- "$@" --wol-interface "$WOL_INTERFACE"
[ "$ADOPT_RETAINED_STATE" -eq 0 ] || set -- "$@" --adopt-retained-state
"$PYTHON_BIN" "$ROOT/scripts/install_core.py" "$@"
if [ -n "$WOL_INTERFACE" ]; then
  printf 'Pinned WOL interface: %s\n' "$WOL_INTERFACE"
  if [ "$CONFIGURE_WOL" -eq 1 ] && [ "$DRY_RUN" -eq 0 ]; then
    "$ROOT/scripts/configure-wol.sh" --interface "$WOL_INTERFACE" --apply
  else
    echo 'Persistent WOL not modified (add --configure-wol to opt in).'
  fi
fi
echo 'Restrict TCP/8765 to your trusted LAN/hub. No firewall rule was changed.'
echo 'Avahi must be installed and running for mDNS discovery.'
echo 'Control key remains in /var/lib/linux-host-agent/control-token (never post it).'
