#!/usr/bin/env python3
"""Unprivileged disposable WOL filesystem acceptance, never live policy.

Prepare in a new private empty directory selected by the tester. Compare
after a normal reboot; rollback explicitly only in that same fixture.
Keep raw identifiers in the private baseline; stdout has fixed evidence.
This is a developer experiment, not the protected production controller.
"""
from __future__ import annotations

import argparse
from contextlib import ExitStack
import json
import os
from pathlib import Path
import stat
import uuid

import wol_fs_identity as identity
import wol_publication as publication


_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
_TXID = 'a' * 32  # fixture-only; never a real installer transaction
_ANCHOR = '.computer-host-wol-' + _TXID + '.stage'
_BASELINE = 'private-baseline.json'
_LIMIT = 16384
_FILES = ('anchor', 'target', 'policy', 'receipt', 'fixture')


def _private(fd: int) -> None:
    st = os.fstat(fd)
    if (not stat.S_ISDIR(st.st_mode) or st.st_uid != os.geteuid() or
            stat.S_IMODE(st.st_mode) != 0o700):
        raise ValueError('fixture must be a private directory')


def _open_directory(stack: ExitStack, name, *, parent=None) -> int:
    fd = os.open(name, _FLAGS, dir_fd=parent)
    stack.callback(os.close, fd)
    _private(fd)
    return fd


def _boot() -> str:
    with open('/proc/sys/kernel/random/boot_id', 'r', encoding='ascii') as stream:
        return str(uuid.UUID(stream.read(128).strip()))


def _sample(fd: int) -> dict:
    before = os.fstat(fd)
    evidence = identity.identify(fd)
    after = os.fstat(fd)
    if (before.st_dev, before.st_ino, before.st_nlink) != (
            after.st_dev, after.st_ino, after.st_nlink):
        raise ValueError('fixture changed during sampling')
    return dict(
        device=after.st_dev, fsid=os.fstatvfs(fd).f_fsid,
        inode=after.st_ino, links=after.st_nlink,
        persistent=(None if evidence is None else
                    [evidence.filesystem, evidence.uuid.hex(),
                     evidence.subvolume, evidence.inode]))


def _snapshot(root: int, policy: int, receipt: int) -> dict:
    with ExitStack() as stack:
        files = {}
        for key, name in (('anchor', _ANCHOR), ('target', publication.TARGET)):
            fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK |
                         os.O_CLOEXEC, dir_fd=policy)
            stack.callback(os.close, fd)
            files[key] = _sample(fd)
        for key, fd in (('fixture', root), ('policy', policy), ('receipt', receipt)):
            files[key] = _sample(fd)
        return dict(schema=1, boot=_boot(), files=files)


def _save(root: int, baseline: dict) -> None:
    raw = (json.dumps(baseline, sort_keys=True) + '\n').encode('ascii')
    if len(raw) > _LIMIT:
        raise ValueError('baseline too large')
    fd = os.open(_BASELINE, os.O_WRONLY | os.O_CREAT | os.O_EXCL |
                 os.O_NOFOLLOW | os.O_CLOEXEC, 0o600, dir_fd=root)
    with os.fdopen(fd, 'wb') as stream:
        stream.write(raw)
        stream.flush()
        os.fchmod(stream.fileno(), 0o600)
        os.fsync(stream.fileno())
    os.fsync(root)


def _load(root: int) -> dict:
    fd = os.open(_BASELINE, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK |
                 os.O_CLOEXEC, dir_fd=root)
    with os.fdopen(fd, 'rb') as stream:
        st = os.fstat(stream.fileno())
        if (not stat.S_ISREG(st.st_mode) or st.st_uid != os.geteuid() or
                st.st_nlink != 1 or stat.S_IMODE(st.st_mode) != 0o600 or
                st.st_size > _LIMIT):
            raise ValueError('unsafe baseline')
        raw = stream.read(_LIMIT + 1)
    if len(raw) > _LIMIT:
        raise ValueError('oversized baseline')
    data = json.loads(raw)
    if (not isinstance(data, dict) or data.get('schema') != 1 or
            not isinstance(data.get('files'), dict) or
            set(data['files']) != set(_FILES)):
        raise ValueError('invalid baseline')
    # Private fixture evidence is advisory; never used to authorize host
    # configuration. Validate the expected shape before comparison.
    uuid.UUID(data['boot'])
    for sample in data['files'].values():
        if (not isinstance(sample, dict) or
                set(sample) != {'device', 'fsid', 'inode', 'links', 'persistent'} or
                any(type(sample[k]) is not int for k in ('device', 'fsid', 'inode', 'links'))):
            raise ValueError('invalid baseline')
    return data


def _available(data: dict) -> bool:
    return all(value['persistent'] is not None for value in data['files'].values())


def _comparison(before: dict, after: dict) -> dict:
    old, new = before['files'], after['files']
    def equal(key):
        return all(old[name][key] == new[name][key] for name in _FILES)
    return dict(
        different_boot=before['boot'] != after['boot'],
        persistent_identity_available=_available(before) and _available(after),
        persistent_identity_unchanged=(_available(before) and _available(after)
                                       and equal('persistent')),
        device_numbers_unchanged=equal('device'),
        filesystem_ids_unchanged=equal('fsid'),
        inode_numbers_unchanged=equal('inode'),
        link_counts_unchanged=equal('links'),
        published_hardlinks_intact=(new['anchor']['links'] == new['target']['links'] == 2
                                    and new['anchor']['device'] == new['target']['device']
                                    and new['anchor']['inode'] == new['target']['inode']))


def experiment(action: str, directory: Path) -> dict:
    """Run only against an explicitly selected private disposable fixture."""
    if action not in ('prepare', 'compare', 'rollback'):
        raise ValueError('unknown action')
    # This tool is never allowed to run with root credentials.
    if os.getuid() == 0 or os.geteuid() == 0:
        raise ValueError('run as an ordinary user, never root')
    with ExitStack() as stack:
        root = _open_directory(stack, directory)
        if action == 'prepare':
            if os.listdir(root):
                raise ValueError('prepare requires an empty private fixture')
            if identity.identify(root) is None:
                return dict(status='identity_unavailable', action=action,
                            secrets_included=False)
            for name in ('policy-fixture', 'receipt-fixture'):
                os.mkdir(name, mode=0o700, dir_fd=root)
            os.fsync(root)
        policy = _open_directory(stack, 'policy-fixture', parent=root)
        receipt = _open_directory(stack, 'receipt-fixture', parent=root)
        uid = os.geteuid()
        if action == 'prepare':
            publication.prepare(policy, receipt, _TXID, owner_uid=uid)
            publication.publish(policy, receipt, _TXID, owner_uid=uid)
            baseline = _snapshot(root, policy, receipt)
            _save(root, baseline)
            return dict(status='prepared', action=action,
                        persistent_identity_available=_available(baseline),
                        published_hardlinks_intact=_comparison(
                            baseline, baseline)['published_hardlinks_intact'],
                        schema2_publication_verified=True, secrets_included=False)
        baseline = _load(root)
        current = _snapshot(root, policy, receipt)
        result = _comparison(baseline, current)
        try:
            verified = publication.inspect(policy, receipt, _TXID,
                                           owner_uid=uid) == 'published'
        except publication.PublicationError:
            verified = False
        result.update(action=action, schema2_publication_verified=verified,
                      secrets_included=False)
        result['status'] = 'compared'
        if action == 'rollback':
            # Deliberately do not bypass schema 2 if f_fsid changed even
            # when the experimental persistent identity agrees.
            if not (verified and result['persistent_identity_unchanged'] and
                    result['published_hardlinks_intact']):
                result['status'] = 'rollback_refused'
                return result
            publication.rollback(policy, receipt, _TXID, owner_uid=uid)
            result['status'] = 'rolled_back'
            result['rollback_verified'] = (
                publication.inspect(policy, receipt, _TXID,
                                    owner_uid=uid) == 'unpublished')
        return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('prepare', 'compare', 'rollback'))
    parser.add_argument('directory', type=Path)
    args = parser.parse_args()
    try:
        result = experiment(args.action, args.directory)
    except (OSError, ValueError, TypeError, KeyError, RecursionError,
            publication.PublicationError):
        # Do not print paths, UUIDs, transaction identifiers or raw errors.
        result = dict(status='fixture_error', action=args.action,
                      secrets_included=False)
    print(json.dumps(result, sort_keys=True))
    return 0 if result['status'] in ('prepared', 'compared', 'rolled_back') else 1


if __name__ == '__main__':
    raise SystemExit(main())
