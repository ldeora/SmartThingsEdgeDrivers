#!/bin/sh
# Installed-only root entry point. NOT a bootstrap or a public installer.
# The approved Go bootstrap must first install this file and the Python
# helpers/manifest as root-owned files under /usr/libexec/computer-host-lan.
# Do not run from a downloaded archive or a source checkout using sudo.
set -eu

[ "$#" -eq 1 ] && [ "$1" = "--request-stdin" ] || {
  echo 'Invalid privileged installer invocation.' >&2
  exit 2
}
[ "$(id -u)" -eq 0 ] || {
  echo 'Privileged installer must run as root.' >&2
  exit 2
}

# Fixed system path, not the invoking user's PATH. Match the normal manual
# installer's ordered list: python3, then python3.14 down to python3.10.
# In particular, RHEL 9 and Leap 15.6 may ship an older default python3.
PATH=/usr/sbin:/usr/bin:/sbin:/bin
export PATH
unset PYTHONPATH PYTHONHOME PYTHONSTARTUP PYTHONUSERBASE
unset LD_PRELOAD LD_LIBRARY_PATH LD_AUDIT
# The caller/bootstrap must already have scrubbed the environment BEFORE
# starting /bin/sh: unset cannot retroactively undo dynamic loader hooks.

PYTHON_BIN=
for candidate in python3 python3.14 python3.13 python3.12 python3.11 python3.10; do
  resolved=$(command -v "$candidate" 2>/dev/null || true)
  case "$resolved" in
    /usr/bin/*|/bin/*) ;;
    *) continue ;;
  esac
  [ -f "$resolved" ] && [ -x "$resolved" ] || continue
  if "$resolved" -I -S -B -c \
    'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' \
    </dev/null >/dev/null 2>&1; then
    PYTHON_BIN=$resolved
    break
  fi
done

[ -n "$PYTHON_BIN" ] || {
  echo 'Python 3.10+ is required (install a compatible system Python interpreter).' >&2
  exit 2
}

# Executable must already be in an independently installed root-owned
# directory. installer_root.py verifies it and all importable modules again
# before processing input or taking any installation action.
exec "$PYTHON_BIN" -I -S -B \
  /usr/libexec/computer-host-lan/installer_root.py --request-stdin
