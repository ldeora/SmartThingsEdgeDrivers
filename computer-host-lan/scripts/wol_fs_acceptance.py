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
import re
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
_SNAPSHOT_KEYS = _FILES + ('link_directory',)
_SYSTEM_LINK_DIRECTORY = ('etc', 'systemd', 'network')


class RootRefused(ValueError):
    pass


class FixtureNotPrivate(ValueError):
    pass


class FixtureNotEmpty(ValueError):
    pass


class BaselineInvalid(ValueError):
    pass


def _private(fd: int) -> None:
    st = os.fstat(fd)
    if (not stat.S_ISDIR(st.st_mode) or st.st_uid != os.geteuid() or
            stat.S_IMODE(st.st_mode) != 0o700):
        raise FixtureNotPrivate()


def _open_directory(stack: ExitStack, name, *, parent=None) -> int:
    fd = os.open(name, _FLAGS, dir_fd=parent)
    stack.callback(os.close, fd)
    _private(fd)
    return fd


def _open_link_directory(stack: ExitStack) -> int | None:
    """Open fixed /etc/systemd/network read-only, without following links.

    This is evidence only. Do not enumerate or read its policy files here.
    Missing, symlinked, writable or non-root-owned components make the
    comparison unavailable; they never make fixture operations fail.
    """
    fd = os.open('/', _FLAGS)
    try:
        for component in _SYSTEM_LINK_DIRECTORY:
            parent = os.fstat(fd)
            if (not stat.S_ISDIR(parent.st_mode) or parent.st_uid != 0 or
                    parent.st_mode & 0o022):
                os.close(fd)
                return None
            child = os.open(component, _FLAGS, dir_fd=fd)
            os.close(fd)
            fd = child
        final = os.fstat(fd)
        if (not stat.S_ISDIR(final.st_mode) or final.st_uid != 0 or
                final.st_mode & 0o022):
            os.close(fd)
            return None
        stack.callback(os.close, fd)
        return fd
    except OSError:
        try:
            os.close(fd)
        except OSError:
            pass
        return None


def _boot() -> str:
    with open('/proc/sys/kernel/random/boot_id', 'r', encoding='ascii') as stream:
        return str(uuid.UUID(stream.read(128).strip()))


def _sample(fd: int) -> dict:
    before = os.fstat(fd)
    evidence = identity.identify(fd)
    after = os.fstat(fd)
    if (before.st_dev, before.st_ino, before.st_nlink, before.st_mode) != (
            after.st_dev, after.st_ino, after.st_nlink, after.st_mode):
        raise ValueError('fixture changed during sampling')
    return dict(
        device=after.st_dev, fsid=os.fstatvfs(fd).f_fsid,
        inode=after.st_ino, links=after.st_nlink,
        persistent=(None if evidence is None else
                    [evidence.filesystem, evidence.uuid.hex(),
                     evidence.subvolume, evidence.inode]))


def _snapshot(root: int, policy: int, receipt: int,
              link_directory: int | None) -> dict:
    with ExitStack() as stack:
        files = {}
        for key, name in (('anchor', _ANCHOR), ('target', publication.TARGET)):
            fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK |
                         os.O_CLOEXEC, dir_fd=policy)
            stack.callback(os.close, fd)
            files[key] = _sample(fd)
        for key, fd in (('fixture', root), ('policy', policy), ('receipt', receipt)):
            files[key] = _sample(fd)
        files['link_directory'] = (
            _sample(link_directory) if link_directory is not None else None)
        return dict(schema=2, boot=_boot(), files=files)


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


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate baseline field')
        result[key] = value
    return result


def _valid_sample(sample: object) -> bool:
    if (type(sample) is not dict or
            set(sample) != {'device', 'fsid', 'inode', 'links', 'persistent'}):
        return False
    if (any(type(sample[k]) is not int for k in ('device', 'fsid', 'inode', 'links'))
            or sample['device'] < 0 or sample['inode'] <= 0 or sample['links'] <= 0):
        return False
    value = sample['persistent']
    if value is None:
        return True
    if (type(value) is not list or len(value) != 4 or
            value[0] not in ('ext4', 'xfs', 'btrfs') or
            not isinstance(value[1], str) or
            re.fullmatch(r'[0-9a-f]{32}', value[1]) is None or
            (value[2] is not None and type(value[2]) is not int) or
            type(value[3]) is not int or value[3] <= 0):
        return False
    return True


def _load(root: int) -> dict:
    try:
        fd = os.open(_BASELINE, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK |
                     os.O_CLOEXEC, dir_fd=root)
        with os.fdopen(fd, 'rb') as stream:
            before = os.fstat(stream.fileno())
            if (not stat.S_ISREG(before.st_mode) or before.st_uid != os.geteuid() or
                    before.st_nlink != 1 or stat.S_IMODE(before.st_mode) != 0o600 or
                    before.st_size > _LIMIT):
                raise ValueError('unsafe baseline')
            raw = stream.read(_LIMIT + 1)
            after = os.fstat(stream.fileno())
            if (len(raw) > _LIMIT or
                    (before.st_dev, before.st_ino, before.st_size,
                     before.st_mtime_ns, before.st_ctime_ns, before.st_nlink) !=
                    (after.st_dev, after.st_ino, after.st_size,
                     after.st_mtime_ns, after.st_ctime_ns, after.st_nlink)):
                raise ValueError('baseline changed during read')
        visible = os.stat(_BASELINE, dir_fd=root, follow_symlinks=False)
        if (visible.st_dev, visible.st_ino, visible.st_ctime_ns) != (
                after.st_dev, after.st_ino, after.st_ctime_ns):
            raise ValueError('baseline replaced during read')
        data = json.loads(raw.decode('ascii'), object_pairs_hook=_unique_object)
        if (type(data) is not dict or set(data) != {'schema', 'boot', 'files'} or
                type(data['schema']) is not int or data['schema'] != 2 or
                not isinstance(data['files'], dict) or
                set(data['files']) != set(_SNAPSHOT_KEYS)):
            raise ValueError('invalid baseline structure')
        if not isinstance(data['boot'], str) or str(uuid.UUID(data['boot'])) != data['boot']:
            raise ValueError('invalid boot identifier')
        for key in _FILES:
            if not _valid_sample(data['files'][key]):
                raise ValueError('invalid fixture sample')
        link_sample = data['files']['link_directory']
        if link_sample is not None and not _valid_sample(link_sample):
            raise ValueError('invalid link directory sample')
        return data
    except (OSError, UnicodeError, ValueError, TypeError, KeyError,
            RecursionError, OverflowError):
        raise BaselineInvalid() from None


def _available(data: dict) -> bool:
    return all(data['files'][name]['persistent'] is not None for name in _FILES)


def _comparison(before: dict, after: dict) -> dict:
    old, new = before['files'], after['files']

    def equal(key):
        return all(old[name][key] == new[name][key] for name in _FILES)

    old_link, new_link = old['link_directory'], new['link_directory']
    old_link_id = None if old_link is None else old_link['persistent']
    new_link_id = None if new_link is None else new_link['persistent']
    link_available = old_link_id is not None and new_link_id is not None
    same_link_fs = bool(
        link_available and old_link_id[:3] == new_link_id[:3] and
        all(old[name]['persistent'] is not None and
            old[name]['persistent'][:3] == old_link_id[:3] and
            new[name]['persistent'] is not None and
            new[name]['persistent'][:3] == new_link_id[:3]
            for name in _FILES))
    return dict(
        different_boot=before['boot'] != after['boot'],
        persistent_identity_available=_available(before) and _available(after),
        persistent_identity_unchanged=(_available(before) and _available(after)
                                       and equal('persistent')),
        device_numbers_unchanged=equal('device'),
        filesystem_ids_unchanged=equal('fsid'),
        inode_numbers_unchanged=equal('inode'),
        link_counts_unchanged=equal('links'),
        link_directory_identity_available=link_available,
        link_directory_identity_unchanged=(
            link_available and old_link_id == new_link_id),
        same_filesystem_and_subvolume_as_link_dir=same_link_fs,
        published_hardlinks_intact=(new['anchor']['links'] == new['target']['links'] == 2
                                    and new['anchor']['device'] == new['target']['device']
                                    and new['anchor']['inode'] == new['target']['inode']))


def experiment(action: str, directory: Path) -> dict:
    """Run only against an explicitly selected private disposable fixture."""
    if action not in ('prepare', 'compare', 'rollback'):
        raise ValueError('unknown action')
    if os.getuid() == 0 or os.geteuid() == 0:
        raise RootRefused()
    return _fixture_experiment(action, directory)


def _fixture_experiment(action: str, directory: Path) -> dict:
    # Internal disposable fixture boundary for CI, including root-run
    # containers. The public CLI and experiment entry point always refuse
    # root; never call this against real policy directories.
    if action not in ('prepare', 'compare', 'rollback'):
        raise ValueError('unknown action')
    with ExitStack() as stack:
        root = _open_directory(stack, directory)
        if action == 'prepare':
            if os.listdir(root):
                raise FixtureNotEmpty()
            if identity.identify(root) is None:
                return dict(status='identity_unavailable', action=action,
                            secrets_included=False)
            for name in ('policy-fixture', 'receipt-fixture'):
                os.mkdir(name, mode=0o700, dir_fd=root)
            os.fsync(root)
        policy = _open_directory(stack, 'policy-fixture', parent=root)
        receipt = _open_directory(stack, 'receipt-fixture', parent=root)
        link_directory = _open_link_directory(stack)
        uid = os.geteuid()
        if action == 'prepare':
            publication.prepare(policy, receipt, _TXID, owner_uid=uid)
            publication.publish(policy, receipt, _TXID, owner_uid=uid)
            baseline = _snapshot(root, policy, receipt, link_directory)
            _save(root, baseline)
            result = _comparison(baseline, baseline)
            return dict(status='prepared', action=action,
                        persistent_identity_available=_available(baseline),
                        link_directory_identity_available=result[
                            'link_directory_identity_available'],
                        same_filesystem_and_subvolume_as_link_dir=result[
                            'same_filesystem_and_subvolume_as_link_dir'],
                        published_hardlinks_intact=result['published_hardlinks_intact'],
                        schema2_publication_verified=True, secrets_included=False)
        baseline = _load(root)
        try:
            state = publication.inspect(policy, receipt, _TXID, owner_uid=uid)
        except publication.PublicationError:
            if action == 'rollback':
                return dict(status='rollback_refused', action=action,
                            schema2_publication_verified=False,
                            secrets_included=False)
            # A changed f_fsid can invalidate the schema-2 receipt while
            # leaving the experimental UUID/subvolume/inode intact.
            # Measure the discrepancy without authorizing any mutation.
            state = None
        if state == 'unpublished':
            return dict(status='fixture_rolled_back', action=action,
                        rollback_verified=True, secrets_included=False)
        current = _snapshot(root, policy, receipt, link_directory)
        result = _comparison(baseline, current)
        result.update(action=action, schema2_publication_verified=(state == 'published'),
                      secrets_included=False)
        result['status'] = ('compared' if state == 'published'
                            else 'compared_ownership_unverified')
        if action == 'rollback':
            # Deliberately do not bypass schema 2 if f_fsid changed even
            # when the experimental persistent identity agrees.
            if not (result['persistent_identity_unchanged'] and
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
    except RootRefused:
        result = dict(status='root_refused', action=args.action,
                      secrets_included=False)
    except FixtureNotPrivate:
        result = dict(status='fixture_not_private', action=args.action,
                      secrets_included=False)
    except FixtureNotEmpty:
        result = dict(status='fixture_not_empty', action=args.action,
                      secrets_included=False)
    except BaselineInvalid:
        result = dict(status='baseline_invalid', action=args.action,
                      secrets_included=False)
    except (OSError, ValueError, TypeError, KeyError, RecursionError,
            publication.PublicationError):
        # Do not print paths, UUIDs, transaction identifiers or raw errors.
        result = dict(status='fixture_error', action=args.action,
                      secrets_included=False)
    print(json.dumps(result, sort_keys=True))
    return 0 if result['status'] in (
        'prepared', 'compared', 'compared_ownership_unverified',
        'rolled_back', 'fixture_rolled_back') else 1


if __name__ == '__main__':
    raise SystemExit(main())
