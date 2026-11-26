"""rc.3 WOL backend: explicit before/after operations, no CLI.

Not yet connected to the protected installer. A caller must hold the
installer locks, persist the exact before/after record before mutation,
and use recovery and ownership records before exposing these operations.
No experimental wol_* modules are imported.
"""
from dataclasses import dataclass
import os
import hashlib
import json
from pathlib import Path
import re
import stat
import subprocess
import tempfile
import uuid


class WolError(RuntimeError):
    pass


_IFACE = re.compile(r"[A-Za-z0-9_.-]{1,15}")
_MAC = re.compile(r"[0-9a-f]{2}(?::[0-9a-f]{2}){5}")
_MODES = re.compile(r"(?:d|[pumbagfs]+)")
_PROPERTY = "802-3-ethernet.wake-on-lan"


def parse_nm_value(output):
    """Normalize documented NM wired WOL flags without losing their bits.

    Accept numeric, numeric-with-description, and symbolic representations.
    Actual nmcli read/write round trips are separately checked in CI.
    """
    flags = {"none": 0, "default": 1, "phy": 2, "unicast": 4,
             "multicast": 8, "broadcast": 16, "arp": 32, "magic": 64,
             "all": 126, "ignore": 32768}
    output = output.strip()
    # nmcli 1.46.0 renders zero WOL flags as an empty value for a
    # successful single-property query. Failed commands still raise.
    if not output:
        return "0"
    match = re.fullmatch(
        r"(0[xX][0-9a-fA-F]{1,8}|[0-9]{1,10})(?: \([A-Za-z0-9_, -]+\))?",
        output)
    if match:
        raw = match[1]
        value = int(raw, 16 if raw.lower().startswith("0x") else 10)
    else:
        words = re.split(r"[,\s]+", output)
        if (not words or any(word not in flags for word in words) or
                (len(words) > 1 and set(words) & {"none", "default", "ignore", "all"})):
            raise WolError("unknown NetworkManager WOL value")
        value = 0
        for word in words:
            value |= flags[word]
    if value not in (0, 1, 32768) and value & ~126:
        raise WolError("NetworkManager WOL value not round-trippable")
    return str(value)


def command(args):
    """Fixed argv only; no shell, inherited environment or interactive input."""
    try:
        result = subprocess.run(args, stdin=subprocess.DEVNULL,
                                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                timeout=10, check=True, text=True,
                                env={"PATH": "/usr/sbin:/usr/bin:/sbin:/bin",
                                     "LANG": "C", "LC_ALL": "C"})
        if len(result.stdout) > 65536:
            raise WolError("unexpected command output")
        return result.stdout
    except (OSError, subprocess.SubprocessError, UnicodeError) as exc:
        raise WolError("WOL command failed") from exc


@dataclass(frozen=True)
class Adapter:
    interface: str
    mac: str
    ifindex: int
    supported: str
    runtime: str


@dataclass(frozen=True)
class Plan:
    adapter: Adapter
    backend: str
    profile: str | None
    previous: str | None
    link_name: str | None
    link_text: str | None = None

    @property
    def owns_change(self):
        return ((self.backend == "nm" and not int(self.previous) & 64) or
                self.backend == "link-create")

    @property
    def nm_after(self):
        if self.backend != "nm":
            return None
        return self.previous if int(self.previous) & 64 else "64"

    @property
    def runtime_after(self):
        return self.adapter.runtime if "g" in self.adapter.runtime else "g"


def visible_policy(plan):
    """Policy fields shown for consent; runtime observations are excluded."""
    return dict(action="configure", interface=plan.adapter.interface,
                mac=plan.adapter.mac, backend=plan.backend, profile=plan.profile,
                previous=plan.previous, link_name=plan.link_name, link_text=plan.link_text)


def policy_digest(plan):
    raw = json.dumps(visible_policy(plan), sort_keys=True, separators=(",", ":"),
                     ensure_ascii=True).encode("ascii")
    return hashlib.sha256(raw).hexdigest()


def preview_policy(interface, *, root=Path("/"), backend=None):
    """Read-only ordinary-user policy inspection; no private record reads."""
    backend = backend if backend is not None else Backend(root=root)
    plan = backend.inspect(interface, preview=True)
    policy = visible_policy(plan)
    text = plan.link_text or ""
    if len(text.encode("utf-8")) > 8192 or any(
            (ord(ch) < 32 and ch not in "\n\t") or 127 <= ord(ch) <= 159 for ch in text):
        raise WolError("link policy too complex for preview")
    policy["digest"] = policy_digest(plan)
    policy["capability"] = "supported" if plan.adapter.supported else "unknown"
    return policy


class Backend:
    def __init__(self, *, root=Path("/"), run=command, owner_uid=0):
        self.root = Path(root)
        self.run = run
        self.owner_uid = owner_uid

    def adapter(self, interface, *, preview=False):
        if (not isinstance(interface, str) or not _IFACE.fullmatch(interface)
                or interface in (".", "..", "lo") or interface.startswith("-")):
            raise WolError("invalid wired interface")
        nic = self.root / "sys/class/net" / interface
        try:
            if ((nic / "type").read_text().strip() != "1"
                    or not (nic / "device").exists()
                    or (nic / "wireless").exists() or (nic / "phy80211").exists()
                    or "DEVTYPE=wlan" in (nic / "uevent").read_text().splitlines()):
                raise WolError("not a wired hardware adapter")
            mac = (nic / "address").read_text().strip().lower()
            index = int((nic / "ifindex").read_text().strip())
            if (not _MAC.fullmatch(mac) or index <= 0 or
                    int(mac[:2], 16) & 1 or mac == "00:00:00:00:00:00"):
                raise WolError("invalid adapter identity")
        except (OSError, ValueError) as exc:
            raise WolError("cannot inspect wired adapter") from exc
        for args in (("ethtool", interface), ("ethtool", "--disable-netlink", interface)):
            try:
                output = self.run(args)
            except WolError:
                continue
            supported = re.findall(r"(?m)^\s*Supports Wake-on:\s*(\S+)\s*$", output)
            runtime = re.findall(r"(?m)^\s*Wake-on:\s*(\S+)\s*$", output)
            if (len(supported) == len(runtime) == 1 and
                    _MODES.fullmatch(supported[0]) and _MODES.fullmatch(runtime[0])):
                if "g" not in supported[0]:
                    raise WolError("magic-packet WOL unsupported")
                # SecureOn passwords cannot be captured/restored by this contract.
                if "s" in runtime[0]:
                    raise WolError("SecureOn runtime policy requires manual configuration")
                return Adapter(interface, mac, index, supported[0], runtime[0])
        if preview:
            return Adapter(interface, mac, index, "", "")
        raise WolError("WOL capability unknown")

    def _nm_active(self):
        output = self.run(("systemctl", "show", "--property=LoadState,ActiveState",
                           "--", "NetworkManager.service"))
        values = dict(line.split("=", 1) for line in output.splitlines() if "=" in line)
        if values == {"LoadState": "loaded", "ActiveState": "active"}:
            return True
        if (values.get("LoadState") in ("loaded", "not-found") and
                values.get("ActiveState") == "inactive"):
            return False
        raise WolError("NetworkManager state unknown")

    def _profile(self, interface):
        value = self.run(("nmcli", "--wait", "5", "-g", "GENERAL.CON-UUID",
                          "device", "show", interface)).strip()
        try:
            if str(uuid.UUID(value)) != value:
                raise ValueError()
        except ValueError as exc:
            raise WolError("no valid active NetworkManager profile") from exc
        return value

    def _nm_value(self, profile):
        output = self.run(("nmcli", "--wait", "5", "-g", _PROPERTY,
                           "connection", "show", "uuid", profile)).strip()
        return parse_nm_value(output)

    def _directory(self, path):
        """Check root-controlled directory ancestry; no symlink traversal."""
        for item in reversed((path, *path.parents)):
            if item == self.root.parent or self.root not in (item, *item.parents):
                continue
            try:
                info = item.lstat()
            except FileNotFoundError:
                continue
            if (not stat.S_ISDIR(info.st_mode) or info.st_uid != self.owner_uid
                    or info.st_mode & 0o022):
                raise WolError("unsafe network configuration directory")

    def _read_link(self, path):
        self._directory(path.parent)
        try:
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            with os.fdopen(fd, "rb") as stream:
                info = os.fstat(stream.fileno())
                if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
                        or info.st_uid != self.owner_uid or info.st_mode & 0o022
                        or info.st_size > 65536):
                    raise WolError("unsafe existing link rule")
                return stream.read(65537).decode("utf-8")
        except (OSError, UnicodeError) as exc:
            raise WolError("cannot inspect existing link rule") from exc

    @staticmethod
    def link_content(mac, selected_text):
        """Retain the vendor default's Link settings; override only WOL."""
        sections = re.split(r"(?m)^[ \t]*\[([^\]\r\n]+)\][ \t]*\r?$",
                            selected_text)
        names = sections[1::2]
        if names.count("Link") != 1 or any(name not in ("Match", "Link")
                                          for name in names):
            raise WolError("default link policy requires manual configuration")
        body = sections[names.index("Link") * 2 + 2]
        if (any(line.rstrip().endswith("\\") for line in body.splitlines()) or
                re.search(r"(?mi)^[ \t]*WakeOnLanPassword[ \t]*=", body)):
            raise WolError("default link policy requires manual configuration")
        lines = [line for line in body.strip("\r\n").splitlines()
                 if not re.match(r"^[ \t]*WakeOnLan[ \t]*=", line, re.I)]
        return ("[Match]\nMACAddress=" + mac + "\n\n[Link]\n" +
                "\n".join(lines).rstrip() + "\nWakeOnLan=magic\n")

    def _link_plan(self, adapter):
        name = "10-linux-host-wol-" + adapter.mac.replace(":", "") + ".link"
        target = self.root / "etc/systemd/network" / name
        # Respect the actual selected rule, not merely a grep match in an
        # unrelated file. Only the vendor default may be shadowed by creation.
        output = self.run(("udevadm", "info", "--query=property",
                           "--path=/sys/class/net/" + adapter.interface))
        selected = [line.split("=", 1)[1] for line in output.splitlines()
                    if line.startswith("ID_NET_LINK_FILE=")]
        dirs = ("etc/systemd/network", "run/systemd/network",
                "usr/local/lib/systemd/network", "usr/lib/systemd/network")
        if len(selected) != 1 or not any(
                Path(selected[0]).parent == Path("/") / directory for directory in dirs):
            raise WolError("effective link rule unknown")
        selected_path = self.root / selected[0].lstrip("/")
        selected_text = self._read_link(selected_path)
        mac_lines = re.findall(r"(?mi)^\s*(?:Permanent)?MACAddress\s*=\s*(.*?)\s*$",
                               selected_text)
        wol_lines = re.findall(r"(?mi)^\s*WakeOnLan\s*=\s*(.*?)\s*$", selected_text)
        if (mac_lines == [adapter.mac] and wol_lines == ["magic"]):
            return Plan(adapter, "link-existing", None, None, None)
        if (selected_path.name != "99-default.link" or
                selected_path.parent not in (self.root / "usr/lib/systemd/network",
                                             self.root / "usr/local/lib/systemd/network")):
            raise WolError("existing link policy " + selected[0] +
                           " requires manual configuration: set WakeOnLan=magic "
                           "in its [Link] section (or generator source), retaining other settings")
        for directory in dirs:
            folder = self.root / directory
            self._directory(folder)
            if not folder.exists():
                continue
            for path in folder.iterdir():
                if path.name.endswith(".link.d") or path.name == "link.d":
                    raise WolError("link drop-ins require manual configuration: "
                                   "review the effective [Link] policy and set WakeOnLan=magic "
                                   "in the administrator configuration")
                if path.name.endswith(".link"):
                    # Do not shadow existing rules or assume that a generic
                    # earlier rule is irrelevant. Also refuse masked rules.
                    text = self._read_link(path)
                    if (path.name <= name or adapter.mac in text.lower()
                            or path == target):
                        raise WolError("existing link rule " + "/" +
                                       str(path.relative_to(self.root)) +
                                       " requires manual configuration: review its [Match] "
                                       "and set WakeOnLan=magic in the appropriate [Link] section")
        return Plan(adapter, "link-create", None, None, name,
                    self.link_content(adapter.mac, selected_text))

    def inspect(self, interface, *, preview=False):
        adapter = self.adapter(interface, preview=preview)
        if self._nm_active():
            profile = self._profile(interface)
            return Plan(adapter, "nm", profile, self._nm_value(profile), None)
        return self._link_plan(adapter)

    def _same_adapter(self, plan):
        now = self.adapter(plan.adapter.interface)
        if (now.mac, now.ifindex) != (plan.adapter.mac, plan.adapter.ifindex):
            raise WolError("adapter changed")
        return now

    def _target(self, plan):
        name = "10-linux-host-wol-" + plan.adapter.mac.replace(":", "") + ".link"
        if plan.link_name != name:
            raise WolError("invalid link target")
        target = self.root / "etc/systemd/network" / name
        self._directory(target.parent)
        return target

    def _create(self, plan):
        target = self._target(plan)
        target.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
        self._directory(target.parent)
        fd, temp = tempfile.mkstemp(prefix=".computer-host-wol-", dir=target.parent)
        try:
            with os.fdopen(fd, "wb") as stream:
                os.fchmod(stream.fileno(), 0o644)
                stream.write(plan.link_text.encode("utf-8"))
                stream.flush()
                os.fsync(stream.fileno())
                created = os.fstat(stream.fileno())
            # Atomic no-clobber. Never replace an administrator file.
            os.link(temp, target, follow_symlinks=False)
        finally:
            os.unlink(temp)
        self._sync_dir(target.parent)
        published = target.lstat()
        if (published.st_dev, published.st_ino) != (created.st_dev, created.st_ino):
            raise WolError("published link identity changed")
        return (created.st_dev, created.st_ino)

    @staticmethod
    def _sync_dir(path):
        fd = os.open(path, os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)

    def apply(self, plan, *, persisted=None):
        """Caller MUST have durably journaled plan before invoking."""
        if self.inspect(plan.adapter.interface) != plan:
            raise WolError("WOL plan changed before application")
        created = None
        if plan.backend == "nm" and plan.previous != plan.nm_after:
            self.run(("nmcli", "--wait", "5", "connection", "modify", "uuid",
                      plan.profile, _PROPERTY, "magic"))
        elif plan.backend == "link-create":
            created = self._create(plan)
        # Confirm the persistent change separately, before any runtime write.
        # The protected caller can durably record ownership at this boundary.
        if plan.backend == "nm" and self._nm_value(plan.profile) != plan.nm_after:
            raise WolError("persistent WOL verification failed")
        if (plan.backend == "link-create" and
                self._read_link(self._target(plan)) != plan.link_text):
            raise WolError("persistent WOL verification failed")
        if persisted is not None:
            persisted(created)
        if plan.adapter.runtime != plan.runtime_after:
            self.run(("ethtool", "-s", plan.adapter.interface, "wol", "g"))
        now = self._same_adapter(plan)
        if now.runtime != plan.runtime_after:
            raise WolError("runtime WOL verification failed")
        if plan.backend == "nm" and self._nm_value(plan.profile) != plan.nm_after:
            raise WolError("persistent WOL verification failed")
        if (plan.backend == "link-create" and
                self._read_link(self._target(plan)) != plan.link_text):
            raise WolError("persistent WOL verification failed")

    def restore(self, plan):
        """Idempotent compensation; refuse externally changed policy.

        This is the immediate rollback primitive, not an uninstall ownership
        validator. A protected caller must establish ownership and validate
        the durable record before calling. Runtime restoration is only for
        the same current adapter identity.
        """
        now = self._same_adapter(plan)
        if now.runtime not in (plan.adapter.runtime, plan.runtime_after):
            raise WolError("runtime WOL changed externally")
        if plan.backend == "nm":
            if not self._nm_active() or self._profile(now.interface) != plan.profile:
                raise WolError("active NetworkManager profile changed")
            current = self._nm_value(plan.profile)
            if current not in (plan.previous, plan.nm_after):
                raise WolError("NetworkManager WOL changed externally")
            if current != plan.previous:
                self.run(("nmcli", "--wait", "5", "connection", "modify", "uuid",
                          plan.profile, _PROPERTY, plan.previous))
            if self._nm_value(plan.profile) != plan.previous:
                raise WolError("NetworkManager restoration failed")
        elif plan.backend == "link-create":
            target = self._target(plan)
            if os.path.lexists(target):
                if self._read_link(target) != plan.link_text:
                    raise WolError("owned link rule changed externally")
                target.unlink()
                self._sync_dir(target.parent)
        if now.runtime != plan.adapter.runtime:
            self.run(("ethtool", "-s", now.interface, "wol", plan.adapter.runtime))
        if self._same_adapter(plan).runtime != plan.adapter.runtime:
            raise WolError("runtime WOL restoration failed")
