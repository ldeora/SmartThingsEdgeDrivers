#!/usr/bin/env sh
# Publish existing capability presentations and localization to SmartThings.
# Cloud mutations are opt-in; by default only print the actions to review.
set -eu
APPLY=0
case "${1:-}" in
  '') ;;
  --apply) APPLY=1 ;;
  *) echo "Usage: $0 [--apply]" >&2; exit 2 ;;
esac
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
CAPDIR="$ROOT/edge-driver/custom-capabilities"
NAMESPACE=oceancircle09600
if [ "$APPLY" -eq 1 ]; then
  command -v smartthings >/dev/null 2>&1 || { echo 'SmartThings CLI missing.' >&2; exit 1; }
fi
for cap in linuxHostStatus linuxCpuUsage linuxMemoryUsage linuxDiskUsage linuxUptime linuxLoad; do
  id="$NAMESPACE.$cap"
  for locale in en de; do
    path="$CAPDIR/$cap.$locale.json"
    [ -f "$path" ] || { echo "Missing $path" >&2; exit 1; }
    echo "smartthings capabilities:translations:upsert $id -i $path"
    if [ "$APPLY" -eq 1 ]; then
      smartthings capabilities:translations:upsert "$id" -i "$path"
    fi
  done
  presentation="$CAPDIR/$cap.presentation.json"
  [ -f "$presentation" ] || { echo "Missing $presentation" >&2; exit 1; }
  echo "smartthings capabilities:presentation:update $id -i $presentation"
  if [ "$APPLY" -eq 1 ]; then
    smartthings capabilities:presentation:update "$id" -i "$presentation"
  fi
done
if [ "$APPLY" -eq 0 ]; then echo 'DRY RUN: run with --apply only after reviewing capability files.'; fi
