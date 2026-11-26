"""Protected persistent WOL ownership, called under the installer locks.

The schema-1 snapshot holds the intended plan. The independent private
record proves whether the persistent write was verified. Never infer
ownership from an identical file or property alone. A crash before
confirmation is deliberately fail-closed if the persistent value changed.
This increment is internal only; public preview/consent and removal follow.
"""
from dataclasses import asdict, replace
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import tempfile
import uuid

import persistent_wol as wol

_MAX_RECORD = 192 * 1024
_HEX = re.compile(r"[0-9a-f]{64}\Z")
_TXID = re.compile(r"[A-Za-z0-9_-]{1,128}\Z")


def _encoded(value):
    raw = (json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True) + "\n").encode("ascii")
    if len(raw) > _MAX_RECORD:
        raise wol.WolError("WOL record exceeds limit")
    return raw


def plan_digest(plan):
    return hashlib.sha256(_encoded(asdict(plan))).hexdigest()


def _uuid(value):
    try:
        return isinstance(value, str) and str(uuid.UUID(value)) == value
    except (ValueError, TypeError, AttributeError):
        return False


def decode_intent(value):
    """Validate bounded, root-originated snapshot metadata before any action."""
    if (type(value) is not dict or set(value) != {"transaction", "boot_id", "plan"}
            or not isinstance(value["transaction"], str)
            or not _TXID.fullmatch(value["transaction"]) or not _uuid(value["boot_id"])):
        raise wol.WolError("invalid WOL snapshot")
    raw = value["plan"]
    if type(raw) is not dict or set(raw) != {
        "adapter", "backend", "profile", "previous", "link_name", "link_text"
    }:
        raise wol.WolError("invalid WOL plan")
    adapter = raw["adapter"]
    if type(adapter) is not dict or set(adapter) != {
        "interface", "mac", "ifindex", "supported", "runtime"
    }:
        raise wol.WolError("invalid WOL adapter")
    name, mac = adapter["interface"], adapter["mac"]
    if (not isinstance(name, str) or not wol._IFACE.fullmatch(name)
            or name in (".", "..", "lo") or name.startswith("-")
            or not isinstance(mac, str) or not wol._MAC.fullmatch(mac)
            or int(mac[:2], 16) & 1 or mac == "00:00:00:00:00:00"
            or type(adapter["ifindex"]) is not int or adapter["ifindex"] <= 0
            or not isinstance(adapter["supported"], str)
            or not wol._MODES.fullmatch(adapter["supported"])
            or "g" not in adapter["supported"]
            or not isinstance(adapter["runtime"], str)
            or not wol._MODES.fullmatch(adapter["runtime"])
            or "s" in adapter["runtime"]):
        raise wol.WolError("invalid WOL adapter")
    plan = wol.Plan(wol.Adapter(**adapter), raw["backend"], raw["profile"],
                    raw["previous"], raw["link_name"], raw["link_text"])
    if plan.backend == "nm":
        if (not _uuid(plan.profile) or not isinstance(plan.previous, str)
                or wol.parse_nm_value(plan.previous) != plan.previous
                or plan.link_name is not None or plan.link_text is not None):
            raise wol.WolError("invalid NetworkManager plan")
    elif plan.backend == "link-create":
        if (plan.profile is not None or plan.previous is not None
                or plan.link_name != "10-linux-host-wol-" + mac.replace(":", "") + ".link"
                or not isinstance(plan.link_text, str)
                or len(plan.link_text.encode("utf-8")) > 65536
                or not plan.link_text.startswith("[Match]\nMACAddress=" + mac + "\n\n[Link]\n")
                or not plan.link_text.endswith("\nWakeOnLan=magic\n")):
            raise wol.WolError("invalid link plan")
    elif plan.backend == "link-existing":
        if any(x is not None for x in (plan.profile, plan.previous, plan.link_name, plan.link_text)):
            raise wol.WolError("invalid existing link plan")
    else:
        raise wol.WolError("invalid WOL backend")
    _encoded(value)
    return plan


class Ownership:
    def __init__(self, *, root=Path("/"), owner_uid=0, backend=None):
        self.root = Path(root)
        self.uid = owner_uid
        self.backend = backend if backend is not None else wol.Backend(
            root=self.root, owner_uid=owner_uid)
        self.directory = self.root / "var/lib/linux-host-agent-installer/wol"

    def boot_id(self):
        value = (self.root / "proc/sys/kernel/random/boot_id").read_text().strip()
        if not _uuid(value):
            raise wol.WolError("boot identity unavailable")
        return value

    def _check_directory(self, *, create=False):
        self.backend._directory(self.directory.parent)
        if not os.path.lexists(self.directory):
            if not create:
                return False
            # The controller has already published the existing owner marker.
            self.directory.mkdir(mode=0o700)
            self.backend._sync_dir(self.directory.parent)
        self.backend._directory(self.directory)
        info = self.directory.lstat()
        if (not stat.S_ISDIR(info.st_mode) or info.st_uid != self.uid
                or stat.S_IMODE(info.st_mode) != 0o700):
            raise wol.WolError("unsafe WOL ownership directory")
        return True

    def _path(self, plan):
        # One record per physical adapter; another adapter gets a separate
        # record. A changed profile on the same adapter needs explicit review.
        return self.directory / (plan.adapter.mac.replace(":", "") + ".json")

    def _read(self, plan):
        if not self._check_directory():
            return None
        try:
            fd = os.open(self._path(plan), os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        except FileNotFoundError:
            return None
        with os.fdopen(fd, "rb") as stream:
            info = os.fstat(stream.fileno())
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != self.uid
                    or info.st_nlink != 1 or stat.S_IMODE(info.st_mode) != 0o600
                    or info.st_size > _MAX_RECORD):
                raise wol.WolError("unsafe WOL ownership record")
            raw = stream.read(_MAX_RECORD + 1)
        try:
            record = json.loads(raw)
            if (type(record) is not dict
                    or set(record) != {"schema", "intent", "state", "inode"}
                    or type(record["schema"]) is not int or record["schema"] != 1
                    or record["state"] not in ("pending", "confirmed")
                    or raw != _encoded(record)):
                raise ValueError()
            saved = decode_intent(record["intent"])
            inode = record["inode"]
            if (saved.adapter.mac != plan.adapter.mac
                    or (inode is not None and (type(inode) is not int or inode <= 0))
                    or (inode is not None) !=
                    (record["state"] == "confirmed" and saved.backend == "link-create")):
                raise ValueError()
            return record
        except (ValueError, TypeError, KeyError, UnicodeError) as exc:
            raise wol.WolError("invalid WOL ownership record") from exc

    def _write(self, plan, record, *, previous=None):
        self._check_directory(create=True)
        if self._read(plan) != previous:
            raise wol.WolError("WOL ownership changed")
        raw = _encoded(record)
        fd, temp = tempfile.mkstemp(prefix=".pending-", dir=self.directory)
        try:
            with os.fdopen(fd, "wb") as stream:
                os.fchmod(stream.fileno(), 0o600)
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            if previous is None:
                os.link(temp, self._path(plan), follow_symlinks=False)
            else:
                os.replace(temp, self._path(plan))
        finally:
            Path(temp).unlink(missing_ok=True)
        self.backend._sync_dir(self.directory)
        if self._read(plan) != record:
            raise wol.WolError("WOL ownership publication failed")

    def _delete(self, plan, record):
        if self._read(plan) != record:
            raise wol.WolError("WOL ownership changed")
        self._path(plan).unlink()
        self.backend._sync_dir(self.directory)

    def prepare(self, interface, digest, transaction):
        if not isinstance(digest, str) or not _HEX.fullmatch(digest):
            raise wol.WolError("invalid WOL approval")
        plan = self.backend.inspect(interface)
        if plan_digest(plan) != digest:
            raise wol.WolError("WOL plan changed before authorization")
        existing = self._read(plan)
        if existing is not None:
            # Do not replace the original baseline on upgrade/reinstall.
            saved = decode_intent(existing["intent"])
            if existing["state"] != "confirmed":
                raise wol.WolError("unfinished WOL ownership")
            if (saved.backend == "nm" and plan.backend == "nm"
                    and saved.profile == plan.profile
                    and plan.previous == saved.nm_after and "g" in plan.adapter.runtime):
                return None
            if (saved.backend == "link-create" and plan.backend == "link-existing"
                    and "g" in plan.adapter.runtime):
                target = self.backend._target(saved)
                if (self.backend._read_link(target) == saved.link_text
                        and target.lstat().st_ino == existing["inode"]):
                    return None
            if (not saved.owns_change and not plan.owns_change
                    and saved.backend == plan.backend and saved.profile == plan.profile
                    and "g" in plan.adapter.runtime):
                return None
            raise wol.WolError("existing WOL ownership requires review")
        intent = {"transaction": transaction, "boot_id": self.boot_id(), "plan": asdict(plan)}
        decode_intent(intent)
        return intent

    def apply(self, intent, transaction):
        plan = decode_intent(intent)
        if intent["transaction"] != transaction or intent["boot_id"] != self.boot_id():
            raise wol.WolError("WOL intent does not match current transaction")
        pending = {"schema": 1, "intent": intent, "state": "pending", "inode": None}
        self._write(plan, pending)

        def confirm():
            inode = None
            if plan.backend == "link-create":
                target = self.backend._target(plan)
                if self.backend._read_link(target) != plan.link_text:
                    raise wol.WolError("WOL link changed before confirmation")
                inode = target.lstat().st_ino
            self._write(plan, dict(pending, state="confirmed", inode=inode), previous=pending)

        self.backend.apply(plan, persisted=confirm)

    def rollback(self, intent, transaction):
        plan = decode_intent(intent)
        if intent["transaction"] != transaction:
            raise wol.WolError("WOL snapshot transaction mismatch")
        record = self._read(plan)
        if record is None:
            # The durable pending record precedes every network mutation.
            return
        if record["intent"] != intent:
            raise wol.WolError("WOL ownership belongs to another transaction")
        same_boot = intent["boot_id"] == self.boot_id()
        now = self.backend.adapter(plan.adapter.interface)
        if (now.mac != plan.adapter.mac or
                (same_boot and now.ifindex != plan.adapter.ifindex)):
            raise wol.WolError("WOL adapter changed")
        if plan.backend == "nm":
            if not self.backend._nm_active() or self.backend._profile(now.interface) != plan.profile:
                raise wol.WolError("WOL profile changed")
            current = self.backend._nm_value(plan.profile)
            if record["state"] == "pending" and current != plan.previous:
                raise wol.WolError("unconfirmed NetworkManager change; manual review required")
        elif plan.backend == "link-create":
            target = self.backend._target(plan)
            if os.path.lexists(target):
                if (record["state"] != "confirmed"
                        or self.backend._read_link(target) != plan.link_text
                        or target.lstat().st_ino != record["inode"]):
                    raise wol.WolError("unconfirmed or changed link; manual review required")
        if record["state"] == "confirmed":
            # Runtime state belongs to this boot. After reboot restore the
            # verified persistent policy, leaving current runtime untouched.
            restore_plan = plan if same_boot else replace(plan, adapter=now)
            self.backend.restore(restore_plan)
        self._delete(plan, record)
