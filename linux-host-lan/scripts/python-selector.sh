#!/usr/bin/env sh
# Shared POSIX-shell Python selection for the Linux Host installer and preflight.
# Source this file. Call linuxhost_select_python [EXPLICIT_ABSOLUTE_PATH].
# Never modifies the distribution's default python3 symlink.
linuxhost_python_compatible() {
  "$1" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' \
    >/dev/null 2>&1
}
linuxhost_safe_python_path() {
  case "$1" in
    /*) ;;
    *) return 1 ;;
  esac
  case "$1" in
    *[!a-zA-Z0-9_./+-]*|'') return 1 ;;
  esac
  [ -f "$1" ] && [ -x "$1" ]
}
linuxhost_select_python() {
  if [ "$#" -gt 0 ] && [ -n "$1" ]; then
    if ! linuxhost_safe_python_path "$1" || ! linuxhost_python_compatible "$1"; then
      echo 'Specified --python must be an executable absolute path to Python 3.10+ (no spaces).' >&2
      return 1
    fi
    LINUXHOST_PYTHON=$1
    return 0
  fi
  for candidate in python3 python3.14 python3.13 python3.12 python3.11 python3.10; do
    resolved=$(command -v "$candidate" 2>/dev/null || true)
    if [ -n "$resolved" ] && linuxhost_safe_python_path "$resolved" && \
       linuxhost_python_compatible "$resolved"; then
      LINUXHOST_PYTHON=$resolved
      return 0
    fi
  done
  echo 'Python 3.10 or newer is required. Install a compatible interpreter or use --python /absolute/path.' >&2
  return 1
}
