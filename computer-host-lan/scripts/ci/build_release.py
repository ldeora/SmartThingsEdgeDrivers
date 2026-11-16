#!/usr/bin/env python3
"""Build source/volunteer-doc archives without embedded pycache or local state.

Versioned top-level directories are preserved in every archive. Builds include
SHA-256 file manifests; final artifact hashes are emitted separately.
"""
from __future__ import annotations

import argparse
import json
import hashlib
from pathlib import Path
import os
import stat
import zipfile

BASE = Path(__file__).resolve().parents[2]
VERSION = json.loads((BASE / 'release.json').read_text(encoding='utf-8'))['integration']
TIMESTAMP = (2026, 11, 16, 12, 0, 0)


def source_files():
    for p in sorted(BASE.rglob('*')):
        if not p.is_file():
            continue
        if p.is_symlink():
            raise RuntimeError(f'Symlink not permitted in source archive: {p}')
        if any(part in ('__pycache__', '.git', '.pytest_cache') for part in p.relative_to(BASE).parts):
            continue
        if p.suffix in ('.pyc', '.pyo'):
            continue
        if p.name in ('FILES.sha256', '.DS_Store'):
            continue
        yield p.relative_to(BASE), p


def write_archive(output: Path, top_dir: str, inputs: list[tuple[Path, Path]], *, include_manifest: bool):
    hashes = []
    with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for rel, p in inputs:
            content = p.read_bytes()
            info = zipfile.ZipInfo(f'{top_dir}/{rel.as_posix()}', date_time=TIMESTAMP)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = ((0o755 if (p.stat().st_mode & stat.S_IXUSR) else 0o644) | stat.S_IFREG) << 16
            z.writestr(info, content, compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
            hashes.append(f'{hashlib.sha256(content).hexdigest()}  {rel.as_posix()}')
        if include_manifest:
            info = zipfile.ZipInfo(f'{top_dir}/FILES.sha256', date_time=TIMESTAMP)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = (stat.S_IFREG | 0o644) << 16
            z.writestr(info, '\n'.join(hashes).encode() + b'\n')
    with zipfile.ZipFile(output) as z:
        assert z.testzip() is None
        assert all(name.startswith(top_dir + '/') for name in z.namelist())
    print(f'{output}: {len(inputs)} files, {output.stat().st_size} bytes')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output-dir', required=True, type=Path)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    full = args.output_dir / f'computer-host-lan-v{VERSION}-source.zip'
    guide = args.output_dir / f'computer-host-lan-v{VERSION}-documentation.zip'
    inputs = list(source_files())
    write_archive(full, f'computer-host-lan-v{VERSION}', inputs, include_manifest=True)
    selected = [(rel, p) for rel, p in inputs
                if str(rel).startswith('docs/development/') or str(rel) in ('README.md', 'PROTOCOL.md', 'INSTALLATION.md', 'SECURITY.md', 'release.json')]
    write_archive(guide, f'computer-host-lan-docs-v{VERSION}', selected, include_manifest=True)
    checksum_file = args.output_dir / f'computer-host-lan-v{VERSION}-SHA256SUMS.txt'
    checksum_file.write_text(''.join(f'{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.name}\n' for p in (full, guide)))
    print(f'Checksums: {checksum_file}')


if __name__ == '__main__':
    main()
