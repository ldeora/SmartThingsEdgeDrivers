#!/usr/bin/env python3
"""Build the root-side SHA-256 manifest from an already-reviewed source tree.

This is a PACKAGING tool, not an installer or an authenticity mechanism.
The resulting manifest MUST be installed from an authenticated release into
the root-owned, fixed trusted launcher directory. Never load a manifest from
the untrusted download next to a wizard at elevated runtime.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys

from installer_root import _MANIFEST_FILES, validate_manifest

_VERSION_LINE = re.compile(rb'''(?m)^VERSION\s*=\s*["']([A-Za-z0-9.+_-]{1,64})["']\s*$''')
_MAX_FILE_SIZE = 1024 * 1024
_MAX_TOTAL = 4 * 1024 * 1024


def build_manifest(source: Path) -> dict:
    source = Path(source)
    files = {}
    total = 0
    version = None
    for name in sorted(_MANIFEST_FILES):
        path = source / name
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW |
                     os.O_NONBLOCK | os.O_CLOEXEC)
        try:
            info = os.fstat(fd)
            if (not stat.S_ISREG(info.st_mode) or
                    not 0 < info.st_size <= _MAX_FILE_SIZE):
                raise ValueError('invalid packaging source')
            contents = os.read(fd, _MAX_FILE_SIZE + 1)
            if len(contents) != info.st_size:
                raise ValueError('invalid packaging source')
            total += len(contents)
            if total > _MAX_TOTAL:
                raise ValueError('oversized packaging source')
            files[name] = hashlib.sha256(contents).hexdigest()
            if name == 'agent/linux_host_agent.py':
                match = _VERSION_LINE.search(contents)
                if match is None:
                    raise ValueError('missing agent VERSION in packaging source')
                version = match.group(1).decode('ascii')
        finally:
            os.close(fd)
    return validate_manifest({
        'schema_version': 1, 'agent_version': version, 'files': files
    })


def main(argv=None) -> int:
    import argparse
    parser = argparse.ArgumentParser(description='Produce trusted installer manifest for packaging')
    parser.add_argument('--source', type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        manifest = build_manifest(args.source)
    except (OSError, ValueError):
        print('Invalid packaging source: cannot produce trusted manifest',
              file=sys.stderr)
        return 2
    print(json.dumps(dict(schema_version=1, **manifest),
                     indent=2, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
