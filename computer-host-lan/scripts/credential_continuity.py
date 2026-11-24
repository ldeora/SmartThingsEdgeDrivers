"""Private, metadata-only credential observations under installer locks.

No persistence, credential content reads or recovery authority. Live account
resolution is internal; explicit account injection is disposable-root only.
"""
from dataclasses import dataclass
from contextlib import ExitStack
import os
import pwd
import grp
from pathlib import Path
import re
import stat


_NAMES = ('installation-id', 'control-token')
_DIR = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
_FILE = os.O_PATH | os.O_NOFOLLOW | os.O_CLOEXEC


class ContinuityError(RuntimeError):
    def __init__(self):
        super().__init__('credential_continuity_unverified')


def _stamp(info):
    return (info.st_dev, info.st_ino, info.st_size, info.st_mode,
            info.st_uid, info.st_gid, info.st_nlink,
            info.st_mtime_ns, info.st_ctime_ns)


def _directory_identity(info):
    # Directory timestamps/link count/size legitimately change on creation.
    return (info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_gid)


@dataclass(frozen=True, repr=False)
class Observation:
    root: Path
    owner_uid: int
    pid: int
    ancestors: tuple
    account: tuple | None
    directory: tuple | None
    credentials: tuple


def _open_optional(stack, parent, name, flags):
    try:
        fd = os.open(name, flags, dir_fd=parent)
    except FileNotFoundError:
        return None
    stack.callback(os.close, fd)
    return fd


def _file(stack, directory, name, account):
    fd = _open_optional(stack, directory, name, _FILE)
    if fd is None:
        return None, None
    info = os.fstat(fd)
    if (not stat.S_ISREG(info.st_mode) or
            (info.st_uid, info.st_gid) != account or
            stat.S_IMODE(info.st_mode) not in (0o400, 0o600) or
            info.st_size == 0 or info.st_nlink not in (1, 2)):
        raise ContinuityError()
    return fd, _stamp(info)


def _walk(root, owner_uid, account):
    with ExitStack() as stack:
        fd = os.open(root, _DIR)
        stack.callback(os.close, fd)
        root_fd = fd
        info = os.fstat(fd)
        root_identity = _directory_identity(info)
        if info.st_uid != owner_uid or info.st_mode & 0o022:
            raise ContinuityError()
        # Keep every ancestor pinned, including the parent of an absence.
        links = []
        absent = []
        for name in ('var', 'lib', 'linux-host-agent'):
            child = _open_optional(stack, fd, name, _DIR)
            if child is None:
                absent.append((fd, name))
                fd = None
                break
            info = os.fstat(child)
            if name == 'linux-host-agent':
                if (account is None or (info.st_uid, info.st_gid) != account or
                        stat.S_IMODE(info.st_mode) != 0o700):
                    raise ContinuityError()
            elif info.st_uid != owner_uid or info.st_mode & 0o022:
                raise ContinuityError()
            links.append((fd, name, child, _directory_identity(info)))
            fd = child
        values = []
        checked = []
        directory = None if fd is None else _directory_identity(os.fstat(fd))
        for name in _NAMES:
            if fd is None:
                values.append(None)
                continue
            item, stamp = _file(stack, fd, name, account)
            if item is None:
                absent.append((fd, name))
                values.append(None)
                continue
            checked.append((fd, name, item, stamp))
            alias = None
            if stamp[6] == 2:
                pattern = re.compile(r'\.' + re.escape(name) + r'\.[0-9a-f]{16}\.tmp')
                matches = []
                with os.scandir(fd) as entries:
                    for count, entry in enumerate(entries):
                        if count >= 4096:
                            raise ContinuityError()
                        if pattern.fullmatch(entry.name) and entry.inode() == stamp[1]:
                            other, other_stamp = _file(stack, fd, entry.name, account)
                            if other is not None and other_stamp == stamp:
                                matches.append(entry.name)
                                checked.append((fd, entry.name, other, other_stamp))
                if len(matches) != 1:
                    raise ContinuityError()
                alias, = matches
            values.append((stamp, alias))
        for parent, name, child, identity in links:
            if (_directory_identity(os.fstat(child)) != identity or
                    _directory_identity(os.stat(name, dir_fd=parent,
                                                follow_symlinks=False)) != identity):
                raise ContinuityError()
        for parent, name, child, stamp in checked:
            if (_stamp(os.fstat(child)) != stamp or
                    _stamp(os.stat(name, dir_fd=parent, follow_symlinks=False)) != stamp):
                raise ContinuityError()
        for parent, name in absent:
            try:
                os.stat(name, dir_fd=parent, follow_symlinks=False)
            except FileNotFoundError:
                continue
            raise ContinuityError()
        if (_directory_identity(os.fstat(root_fd)) != root_identity or
                _directory_identity(os.stat(root, follow_symlinks=False)) != root_identity):
            raise ContinuityError()
        ancestors = (root_identity,) + tuple(link[3] for link in links)
        return Observation(root, owner_uid, os.getpid(), ancestors, account,
                           directory, tuple(values))


def observe(root, *, owner_uid, account):
    """Capture twice on a disposable root; account is (uid, gid) or absent."""
    root = Path(root)
    try:
        if (not root.is_absolute() or root == Path('/') or root.resolve() != root or
                type(owner_uid) is not int or owner_uid < 0 or
                (account is not None and (type(account) is not tuple or len(account) != 2 or
                 any(type(value) is not int or value < 0 for value in account)))):
            raise ContinuityError()
        first = _walk(root, owner_uid, account)
        if _walk(root, owner_uid, account) != first:
            raise ContinuityError()
        return first
    except (OSError, ValueError, RuntimeError) as exc:
        if isinstance(exc, ContinuityError):
            raise
        raise ContinuityError() from None


def _live_account():
    try:
        user = pwd.getpwnam('linuxhost')
    except KeyError:
        user = None
    try:
        group = grp.getgrnam('linuxhost')
    except KeyError:
        group = None
    if user is None and group is None:
        return None
    if (user is None or group is None or user.pw_name != 'linuxhost' or
            group.gr_name != 'linuxhost' or user.pw_uid <= 0 or
            user.pw_gid <= 0 or user.pw_gid != group.gr_gid or
            user.pw_dir != '/var/lib/linux-host-agent' or
            user.pw_shell not in ('/usr/sbin/nologin', '/sbin/nologin',
                                  '/usr/bin/nologin', '/bin/false', '/usr/bin/false')):
        raise ContinuityError()
    return user.pw_uid, user.pw_gid


def observe_live():
    """Resolve account twice under the caller's live installer locks."""
    if os.geteuid() != 0:
        raise ContinuityError()
    try:
        account = _live_account()
        first = _walk(Path('/'), 0, account)
        if (_live_account() != account or
                _walk(Path('/'), 0, account) != first or
                _live_account() != account):
            raise ContinuityError()
        return first
    except (OSError, ValueError, RuntimeError):
        raise ContinuityError() from None


@dataclass(frozen=True)
class Result:
    """Only bounded, public outcome enums; never a metadata observation."""
    installation_id: str = 'not_verified'
    control_token: str = 'not_verified'
    reason: str = ''

    def public(self):
        allowed = ('verified', 'absent', 'newly_present', 'not_verified')
        if (self.installation_id not in allowed or self.control_token not in allowed or
                self.reason not in ('', 'credential_continuity_unverified',
                                    'continuity_unverified_after_interruption') or
                (self.reason and (self.installation_id, self.control_token) !=
                 ('not_verified', 'not_verified'))):
            raise ContinuityError()
        return dict(installation_id_continuity=self.installation_id,
                    control_token_continuity=self.control_token,
                    credential_continuity=('verified' if self.installation_id ==
                                           self.control_token == 'verified' else 'not_verified'),
                    continuity_reason=self.reason)


class Check:
    """One invocation/handle only. Any comparison failure is sticky."""
    def __init__(self, journal, observe):
        self._journal = journal
        self._observe = observe
        self._before = None
        self.failed = False
        self.result = Result()

    def capture(self):
        try:
            if self._before is not None or self.failed:
                raise ContinuityError()
            self._before = self._observe()
        except ContinuityError:
            self.fail()
            raise

    def fail(self):
        self.failed = True
        self.result = Result(reason='credential_continuity_unverified')

    def verify(self, journal, *, allow_new=False):
        try:
            if self.failed or journal is not self._journal or self._before is None:
                raise ContinuityError()
            states = compare(self._before, self._observe(), allow_new=allow_new)
            self.result = Result(states['installation-id'], states['control-token'])
            return self.result
        except ContinuityError:
            self.fail()
            raise


def compare(before, after, *, allow_new=False):
    """Return only fixed per-credential statuses, or refuse the comparison."""
    if (type(before) is not Observation or type(after) is not Observation or
            before.root != after.root or before.owner_uid != after.owner_uid or
            before.pid != os.getpid() or after.pid != before.pid or
            after.ancestors[:len(before.ancestors)] != before.ancestors or
            (before.account is not None and before.account != after.account) or
            (before.directory is not None and before.directory != after.directory) or
            (not allow_new and (before.account != after.account or
                                before.directory != after.directory))):
        raise ContinuityError()
    result = {}
    for name, old, new in zip(_NAMES, before.credentials, after.credentials):
        if old is None:
            if new is not None and not allow_new:
                raise ContinuityError()
            result[name] = 'absent' if new is None else 'newly_present'
        elif new == old:
            result[name] = 'verified'
        else:
            raise ContinuityError()
    return result
