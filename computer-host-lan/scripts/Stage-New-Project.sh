#!/usr/bin/env bash
# Stage the self-contained computer-host-lan project into an existing checkout.
# Never modifies linux-host-lan/ or pushes without explicit user review.
set -euo pipefail
if [[ $# -ne 1 ]]; then
  echo 'Usage: scripts/Stage-New-Project.sh /path/to/SmartThingsEdgeDrivers' >&2; exit 2
fi
source_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
repo="$(cd "$1" && git rev-parse --show-toplevel)"
[[ -d "$repo/linux-host-lan" ]] || { echo 'Expected existing linux-host-lan/ project' >&2; exit 1; }
if [[ -e "$repo/computer-host-lan" ]]; then
  # Accept only the initial README scaffold created on feature/computer-host-lan.
  extras="$(find "$repo/computer-host-lan" -type f ! -name README.md -print -quit)"
  [[ -z "$extras" ]] || { echo 'computer-host-lan/ contains other files; refusing to overwrite' >&2; exit 1; }
fi
mkdir -p "$repo/computer-host-lan" "$repo/.github/workflows"
cp -a "$source_root"/. "$repo/computer-host-lan/"
cp "$source_root/.github/workflows/windows-agent.yml" "$repo/.github/workflows/computer-host-windows.yml"
cp "$source_root/.github/workflows/tests.yml" "$repo/.github/workflows/computer-host-linux.yml"
(
 cd "$repo"
 git add computer-host-lan .github/workflows/computer-host-windows.yml .github/workflows/computer-host-linux.yml
 git status --short
)
echo 'Only staged; inspect git diff --cached before committing and pushing.'
