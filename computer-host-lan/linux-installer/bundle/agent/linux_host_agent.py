#!/usr/bin/env python3
"""Linux Host Agent: bounded read-mostly HTTP endpoint for SmartThings.

Power control is opt-in, HMAC authenticated with one-time 30-second nonces, and
forwarded to a separate, restricted root-side Unix socket helper. The listener
runs unprivileged and never executes arbitrary shell commands.

HMAC prevents sending the shared secret over the wire, but HTTP has NO channel
confidentiality. Do not expose this service outside a trusted, isolated LAN.
"""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import ipaddress
import json
import os
from pathlib import Path
import platform
import secrets
import socket
import socketserver
import struct
import sys
import threading
import time
import uuid

PROTOCOL = "computer-host-agent"
VERSION = "0.4.6-rc.2"
API_VERSION = 2
ALLOWED_ACTIONS = frozenset(("shutdown", "reboot", "suspend"))
MAX_REPLY_BYTES = 32 * 1024
CLIENT_IO_TIMEOUT_SECONDS = 4.0
MAX_CONCURRENT_CLIENTS = 12
MAX_CONCURRENT_CLIENTS_PER_SOURCE = 4
MAX_HTTP_HEADER_BYTES = 12 * 1024
MAX_HTTP_HEADER_SECONDS = 5.0
CHALLENGE_LIMIT_PER_IP = 20  # per rolling minute; protects nonce allocation
CHALLENGE_LIMIT_GLOBAL = 120
MAX_PENDING_NONCES = 128


def state_dir() -> Path:
    sd = os.environ.get("STATE_DIRECTORY")
    if sd:
        return Path(sd.split(":")[0])
    return Path.home() / ".local" / "state" / "linux-host-agent"


def persistent_value(path: Path, create, validate) -> str:
    """Publish fresh identity/token atomically; never replace an existing value.

    An interrupted first startup can leave an unreferenced private temporary
    file, but cannot leave a partial installation-id or control-token.
    """
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if path.is_symlink():
        raise RuntimeError(f"Refusing symlinked private state: {path}")
    if not path.exists():
        temporary = path.with_name(f".{path.name}.{secrets.token_hex(8)}.tmp")
        fd = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
        try:
            with os.fdopen(fd, "w", encoding="ascii") as out:
                out.write(create() + "\n")
                out.flush()
                os.fsync(out.fileno())
            try:
                os.link(temporary, path, follow_symlinks=False)
                directory_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
            except FileExistsError:
                # Another startup won the race; read its published value.
                pass
        finally:
            temporary.unlink(missing_ok=True)
    try:
        if path.is_symlink():
            raise ValueError("private state cannot be a symbolic link")
        value = path.read_text(encoding="ascii").strip()
        if path.stat().st_mode & 0o077:
            raise ValueError("private state file must have mode 0600 or more restrictive")
        if not validate(value):
            raise ValueError("invalid stored value")
        return value
    except (OSError, ValueError) as exc:
        raise RuntimeError(f"Corrupt or insecure state at {path}: {exc}") from exc

def installation_id(path: Path) -> str:
    return persistent_value(path, lambda: str(uuid.uuid4()),
                            lambda x: len(x) == 36 and str(uuid.UUID(x)) == x)


def control_secret(path: Path) -> str:
    return persistent_value(path, lambda: secrets.token_hex(32),
                            lambda x: len(x) == 64 and all(c in "0123456789abcdef" for c in x))


def read_first(path: str) -> str | None:
    try:
        return Path(path).read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError):
        return None


def boot_id() -> str | None:
    return read_first("/proc/sys/kernel/random/boot_id")


def uptime_seconds() -> float | None:
    raw = read_first("/proc/uptime")
    try:
        return round(float(raw.split()[0]), 1) if raw else None
    except (ValueError, IndexError):
        return None


def os_label() -> str:
    try:
        data = platform.freedesktop_os_release()
        return data.get("PRETTY_NAME", data.get("NAME", "Linux"))
    except (OSError, AttributeError):
        return "Linux"


def parse_cpu_stat(raw: str | None) -> tuple[int, int] | None:
    if not raw:
        return None
    first = raw.splitlines()[0].split()
    if len(first) < 5 or first[0] != "cpu":
        return None
    try:
        vals = [int(x) for x in first[1:]]
    except ValueError:
        return None
    idle = vals[3] + (vals[4] if len(vals) > 4 else 0)
    return sum(vals), idle


def memory_details(raw: str | None) -> tuple[int | None, float | None, int | None, int | None]:
    """Physical RAM total/percent/used/available, using MemAvailable.

    MemFree excludes reclaimable cache; MemAvailable estimates allocatable
    RAM without swapping. Keep current utilization-percent semantics.
    """
    vals = {}
    if raw:
        for line in raw.splitlines():
            if ":" in line:
                key, value = line.split(":", 1)
                try:
                    vals[key] = int(value.split()[0]) * 1024
                except (ValueError, IndexError):
                    continue
    total = vals.get("MemTotal")
    available = vals.get("MemAvailable")
    if not total or available is None or not 0 <= available <= total:
        return None, None, None, None
    used = total - available
    return total, round(100 * used / total, 1), used, available


def memory_metrics(raw: str | None) -> tuple[int | None, float | None]:
    """Backward-compatible total and percentage helper."""
    total, percent, _, _ = memory_details(raw)
    return total, percent


def disk_details(path: str = "/") -> tuple[float | None, int | None, int | None, int | None]:
    """Existing usage percent, filesystem size, used and available bytes.

    f_bfree is actual free space; f_bavail excludes reserved blocks. Used
    plus available can therefore be less than total (as with df and quotas).
    Existing percentage stays (total - available) / total, unchanged.
    """
    try:
        stat = os.statvfs(path)
        total = stat.f_blocks * stat.f_frsize
        available = stat.f_bavail * stat.f_frsize
        if total <= 0 or not 0 <= available <= total:
            return None, None, None, None
        percent = round(100 * (total - available) / total, 1)
        free_blocks = getattr(stat, "f_bfree", None)
        if not isinstance(free_blocks, int) or not 0 <= free_blocks <= stat.f_blocks:
            # Preserve existing values if used-block accounting is unavailable.
            return percent, total, None, available
        used = (stat.f_blocks - free_blocks) * stat.f_frsize
        return percent, total, used, available
    except OSError:
        return None, None, None, None


def disk_metrics(path: str = "/") -> tuple[float | None, int | None]:
    """Backward-compatible percentage and total helper."""
    percent, total, _, _ = disk_details(path)
    return percent, total


def disk_used_percent(path: str = "/") -> float | None:
    """Backward-compatible percentage helper."""
    return disk_metrics(path)[0]


def choose_temperature(override: str | None = None) -> tuple[float | None, str | None]:
    """Prefer core CPU hwmon sources; do not mislabel an NVMe reading as CPU."""
    if override:
        p = Path(override)
        if not str(p).startswith(("/sys/class/hwmon/", "/sys/class/thermal/")):
            return None, None
        candidates = [(0, p, "custom")]
    else:
        candidates = []
        for p in Path("/sys/class/hwmon").glob("hwmon*/temp*_input"):
            chip = read_first(str(p.parent / "name")) or ""
            if chip.lower() not in {"coretemp", "k10temp", "zenpower", "cpu_thermal", "acpitz", "soc_thermal"}:
                continue
            label = read_first(str(p).replace("_input", "_label")) or ""
            prio = 0 if "package" in label.lower() or "tctl" in label.lower() else 1
            candidates.append((prio, p, f"{chip} {label}".strip()))
        for p in Path("/sys/class/thermal").glob("thermal_zone*/temp"):
            label = read_first(str(p.parent / "type")) or ""
            if any(x in label.lower() for x in ("cpu", "x86_pkg", "soc_thermal")):
                candidates.append((2, p, label))
    for _, path, label in sorted(candidates, key=lambda x: (x[0], str(x[1]))):
        raw = read_first(str(path))
        try:
            temp = float(raw) / 1000
            if -40 <= temp <= 150:
                return round(temp, 1), label
        except (TypeError, ValueError):
            continue
    return None, None


def default_interface() -> str | None:
    """Find an IPv4 LAN interface at request time, not at process startup.

    ``network.target`` doesn't wait for an IPv4 default route to appear.  A
    failed selection must therefore be retried on subsequent /v2/info calls.
    Prefer physical Ethernet NICs, not tunnels (such as tailscale0), and use
    an IPv4-addressed physical NIC when an isolated LAN has no default route.
    For unusual topologies users can supply --wol-interface explicitly.
    """
    routes = []
    raw = read_first("/proc/net/route")
    if raw:
        for line in raw.splitlines()[1:]:
            columns = line.split()
            if len(columns) < 8 or columns[1] != "00000000":
                continue
            try:
                if not (int(columns[3], 16) & 1):
                    continue
                metric = int(columns[6])
            except ValueError:
                continue
            iface = columns[0]
            if (Path("/sys/class/net") / iface / "device").exists():
                routes.append((metric, iface))
    for _, iface in sorted(routes):
        # An IP and a broadcast address are needed for reliable automatic WOL.
        if network_details(iface)["wol_broadcast"]:
            return iface

    # A home LAN may not have a default route (or its route may arrive later).
    # Only choose physical NICs, never loopback, tun/tap, VPN, or a bridge MAC.
    try:
        interfaces = sorted(Path("/sys/class/net").iterdir())
    except OSError:
        interfaces = []
    for entry in interfaces:
        if entry.name != "lo" and (entry / "device").exists():
            details = network_details(entry.name)
            if details["wol_mac"] and details["wol_broadcast"]:
                return entry.name
    return None


def network_details(interface: str | None) -> dict:
    if not interface or not interface.replace("-", "").replace("_", "").replace(".", "").isalnum():
        return {"wol_mac": None, "wol_broadcast": None, "wol_interface": None}
    raw = read_first(f"/sys/class/net/{interface}/address")
    try:
        octets = [int(x, 16) for x in raw.split(":")]
        if len(octets) != 6 or octets == [0] * 6 or octets[0] & 1:
            raw = None
    except (AttributeError, ValueError):
        raw = None
    broadcast = None
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            ifname = interface.encode("ascii")[:15]
            addr = fcntl.ioctl(sock.fileno(), 0x8915, struct.pack("256s", ifname))
            mask = fcntl.ioctl(sock.fileno(), 0x891b, struct.pack("256s", ifname))
        ip = socket.inet_ntoa(addr[20:24])
        netmask = socket.inet_ntoa(mask[20:24])
        net = ipaddress.IPv4Network(f"{ip}/{netmask}", strict=False)
        broadcast = str(net.broadcast_address)
    except (OSError, ValueError):
        pass
    return {"wol_mac": raw, "wol_broadcast": broadcast, "wol_interface": interface}


class MetricsSampler:
    def __init__(self, temperature_path: str | None):
        self.lock = threading.Lock()
        self.last_cpu: tuple[int, int] | None = None
        self.temperature_path = temperature_path

    def sample(self) -> dict:
        now = parse_cpu_stat(read_first("/proc/stat"))
        cpu_percent = None
        with self.lock:
            previous = self.last_cpu
            self.last_cpu = now
        if now and previous:
            total = now[0] - previous[0]
            idle = now[1] - previous[1]
            if total > 0:
                cpu_percent = round(100 * max(0, min(1, (total - idle) / total)), 1)
        total_mem, memory_percent, memory_used, memory_available = memory_details(read_first("/proc/meminfo"))
        disk_percent, disk_total, disk_used, disk_available = disk_details()
        temp, temp_label = choose_temperature(self.temperature_path)
        try:
            loads = [round(x, 2) for x in os.getloadavg()]
        except OSError:
            loads = [None, None, None]
        return {
            "cpu_usage_percent": cpu_percent,
            "memory_usage_percent": memory_percent,
            "memory_total_bytes": total_mem,
            "memory_used_bytes": memory_used,
            "memory_available_bytes": memory_available,
            "cpu_temperature_c": temp,
            "cpu_temperature_label": temp_label,
            "disk_root_usage_percent": disk_percent,
            "disk_root_total_bytes": disk_total,
            "disk_root_used_bytes": disk_used,
            "disk_root_available_bytes": disk_available,
            "load_1m": loads[0], "load_5m": loads[1], "load_15m": loads[2],
            "uptime_seconds": uptime_seconds(),
            "boot_id": boot_id(),
        }


class NonceCapacityError(Exception):
    """The bounded challenge store is full; never evict live challenges."""


class Nonces:
    def __init__(self, *, max_pending: int = MAX_PENDING_NONCES, ttl: float = 30.0):
        self.lock = threading.Lock()
        self.tokens: dict[str, float] = {}
        self.max_pending = max_pending
        self.ttl = ttl

    def issue(self) -> str:
        with self.lock:
            now = time.monotonic()
            # Expire lazily, without invalidating any still-live challenge.
            self.tokens = {k: exp for k, exp in self.tokens.items() if exp > now}
            if len(self.tokens) >= self.max_pending:
                raise NonceCapacityError("challenge capacity reached")
            token = secrets.token_hex(24)
            self.tokens[token] = now + self.ttl
            return token

    def consume(self, token: str) -> bool:
        with self.lock:
            deadline = self.tokens.pop(token, 0)
        return bool(deadline > time.monotonic())


class ChallengeRateLimiter:
    """Small bounded fixed-window limiter; independent of unauthenticated input.

    The per-IP limit covers ordinary abuse, and the global limit prevents an
    attacker with multiple addresses from unbounded challenge allocation.
    """
    def __init__(self, per_ip: int = CHALLENGE_LIMIT_PER_IP,
                 global_limit: int = CHALLENGE_LIMIT_GLOBAL,
                 window: float = 60.0, max_clients: int = 256):
        self.lock = threading.Lock()
        self.per_ip = per_ip
        self.global_limit = global_limit
        self.window = window
        self.max_clients = max_clients
        self.clients: dict[str, tuple[float, int]] = {}
        self.global_since = time.monotonic()
        self.global_count = 0

    def permit(self, ip: str) -> bool:
        now = time.monotonic()
        with self.lock:
            if now - self.global_since >= self.window:
                self.global_since, self.global_count = now, 0
                self.clients.clear()
            since, count = self.clients.get(ip, (now, 0))
            if now - since >= self.window:
                since, count = now, 0
            if self.global_count >= self.global_limit or count >= self.per_ip:
                return False
            if ip not in self.clients and len(self.clients) >= self.max_clients:
                # Reject new addresses instead of dropping limits for others.
                return False
            self.clients[ip] = (since, count + 1)
            self.global_count += 1
            return True


class HeaderBudgetReader:
    """Enforce per-request HTTP header byte and elapsed-time budgets.

    The reader checks the deadline between reads and limits socket inactivity.
    Handler's independent timer interrupts a blocked BufferedReader.readline(),
    so a peer cannot extend the absolute deadline by drip-feeding bytes.
    """
    def __init__(self, reader, conn: socket.socket, *, io_timeout: float,
                 max_bytes: int = MAX_HTTP_HEADER_BYTES,
                 deadline_seconds: float = MAX_HTTP_HEADER_SECONDS):
        self.reader = reader
        self.conn = conn
        self.io_timeout = io_timeout
        self.max_bytes = max_bytes
        self.deadline_seconds = deadline_seconds
        self.begin_request()

    def begin_request(self) -> None:
        """Reset the budgets before reading one request line and its headers."""
        self.used = 0
        self.deadline = time.monotonic() + self.deadline_seconds

    def readline(self, limit: int = -1) -> bytes:
        remaining = self.deadline - time.monotonic()
        if remaining <= 0 or self.used >= self.max_bytes:
            raise TimeoutError('HTTP header time or size budget exceeded')
        self.conn.settimeout(min(self.io_timeout, remaining))
        allowance = self.max_bytes - self.used + 1
        bound = min(allowance, limit) if limit >= 0 else allowance
        data = self.reader.readline(bound)
        self.used += len(data)
        if self.used > self.max_bytes:
            raise TimeoutError('HTTP header byte budget exceeded')
        return data

    def __getattr__(self, name):
        return getattr(self.reader, name)


class BoundedHTTPServer(ThreadingHTTPServer):
    """Bound accepted connections, request parsing time and active handlers.

    Excess clients are closed by the accept loop *without* spawning threads.
    A source address can hold at most four of the twelve default handler slots;
    neither the port nor client-provided headers affect the source identity.
    This is a resource bound, not authentication or a distributed DoS defense.
    """
    daemon_threads = True
    block_on_close = False
    request_queue_size = 16
    allow_reuse_address = True

    def __init__(self, server_address, request_handler_class,
                 max_clients: int = MAX_CONCURRENT_CLIENTS,
                 io_timeout: float = CLIENT_IO_TIMEOUT_SECONDS,
                 header_timeout: float = MAX_HTTP_HEADER_SECONDS):
        self._slots = threading.BoundedSemaphore(max_clients)
        self._client_lock = threading.Lock()
        self._active_by_source: dict[str, int] = {}
        self.io_timeout = io_timeout
        self.header_timeout = header_timeout
        super().__init__(server_address, request_handler_class)

    def get_request(self):
        sock, addr = super().get_request()
        sock.settimeout(self.io_timeout)
        return sock, addr

    def _admit_client(self, source: str) -> bool:
        with self._client_lock:
            count = self._active_by_source.get(source, 0)
            if count >= MAX_CONCURRENT_CLIENTS_PER_SOURCE:
                return False
            if not self._slots.acquire(blocking=False):
                return False
            self._active_by_source[source] = count + 1
            return True

    def _release_client(self, source: str) -> None:
        with self._client_lock:
            count = self._active_by_source[source]
            if count == 1:
                del self._active_by_source[source]
            else:
                self._active_by_source[source] = count - 1
            self._slots.release()

    def process_request(self, request, client_address):
        source = client_address[0]
        if not self._admit_client(source):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self._release_client(source)
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._release_client(client_address[0])


def signature(secret_hex: str, path: str, nonce: str) -> str:
    data = f"POST\n{path}\n{nonce}\n".encode("ascii")
    return hmac.new(bytes.fromhex(secret_hex), data, hashlib.sha256).hexdigest()


def request_power(sockpath: str, action: str, timeout: float = 3.5) -> None:
    if action not in ALLOWED_ACTIONS:
        raise ValueError("invalid action")
    response = bytearray()
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
        s.settimeout(timeout)
        s.connect(sockpath)
        s.sendall((action + "\n").encode("ascii"))
        # Unix stream sockets may split even a tiny reply across recv calls.
        while len(response) < 32 and b"\n" not in response:
            chunk = s.recv(32 - len(response))
            if not chunk:
                break
            response.extend(chunk)
    if bytes(response) != b"OK\n":
        raise RuntimeError("power helper rejected the request")


class AgentState:
    def __init__(self, identifier: str, secret: str, enable_power: bool,
                 helper_socket: str, interface: str | None, temperature_path: str | None):
        self.identifier = identifier
        self.secret = secret
        self.enable_power = enable_power
        self.helper_socket = helper_socket
        self.interface = interface
        self.nonces = Nonces()
        self.challenge_limits = ChallengeRateLimiter()
        self.metrics = MetricsSampler(temperature_path)

    def info(self) -> dict:
        actions = sorted(ALLOWED_ACTIONS) if self.enable_power else []
        return {"protocol": PROTOCOL, "api_version": API_VERSION,
                "agent_version": VERSION, "id": self.identifier,
                "hostname": socket.gethostname(), "platform": "linux", "os": os_label(),
                "features": ["health", "metrics", "wol-metadata"] + (["power-control"] if actions else []),
                "power_actions": actions,
                **network_details(self.interface or default_interface())}


def make_handler(state: AgentState):
    class Handler(BaseHTTPRequestHandler):
        server_version = "LinuxHostAgent/" + VERSION
        sys_version = ""

        def setup(self):
            super().setup()
            self.header_timeout = getattr(self.server, "header_timeout", MAX_HTTP_HEADER_SECONDS)
            self.rfile = HeaderBudgetReader(
                self.rfile, self.connection,
                io_timeout=getattr(self.server, "io_timeout", CLIENT_IO_TIMEOUT_SECONDS),
                deadline_seconds=self.header_timeout,
            )
            self._header_deadline_lock = threading.Lock()
            self._header_read_complete = threading.Event()
            self._header_read_complete.set()
            self._header_deadline_expired = False
            self._header_deadline_timer = None

        def _begin_header_read(self):
            with self._header_deadline_lock:
                self._header_read_complete.clear()
                self._header_deadline_expired = False
                self.rfile.begin_request()
                timer = threading.Timer(self.header_timeout, self._expire_header_read)
                timer.daemon = True
                self._header_deadline_timer = timer
                timer.start()

        def _expire_header_read(self):
            with self._header_deadline_lock:
                if self._header_read_complete.is_set():
                    return
                self._header_deadline_expired = True
                # shutdown() interrupts a BufferedReader.readline() that is
                # still receiving bytes; a socket inactivity timeout alone
                # cannot enforce an absolute deadline against a slow drip.
                try:
                    self.connection.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass

        def _finish_header_read(self):
            with self._header_deadline_lock:
                # The timer thread can be scheduled late under load. Check
                # the clock here as well so a just-finished slow read cannot
                # win a race and cancel an already-expired deadline.
                if (not self._header_read_complete.is_set()
                        and time.monotonic() >= self.rfile.deadline):
                    self._header_deadline_expired = True
                    try:
                        self.connection.shutdown(socket.SHUT_RDWR)
                    except OSError:
                        pass
                self._header_read_complete.set()
                timer = self._header_deadline_timer
                self._header_deadline_timer = None
                if timer is not None:
                    timer.cancel()

        def handle_one_request(self):
            self._begin_header_read()
            try:
                return super().handle_one_request()
            except OSError:
                # Only suppress socket failures while the request line or
                # headers are still being read. Preserve unexpected OSErrors
                # from endpoint processing for normal server error handling.
                if self._header_read_complete.is_set() and not self._header_deadline_expired:
                    raise
                self.close_connection = True
                return
            finally:
                self._finish_header_read()

        def parse_request(self):
            try:
                return super().parse_request()
            except OSError:
                # A peer disconnect or deadline shutdown during header parsing
                # is connection-local and must not escape the handler thread.
                self.close_connection = True
                return False
            finally:
                # Stop the timer immediately after the headers are parsed,
                # before endpoint processing or response generation.
                self._finish_header_read()

        def do_GET(self):
            if self.path == "/v2/info":
                return self.reply(state.info())
            if self.path == "/v2/health":
                return self.reply({"protocol": PROTOCOL, "api_version": API_VERSION,
                                   "id": state.identifier, "platform": "linux", "status": "running",
                                   "boot_id": boot_id(), "uptime_seconds": uptime_seconds()})
            if self.path == "/v2/metrics":
                return self.reply({"protocol": PROTOCOL, "api_version": API_VERSION,
                                   "id": state.identifier, "platform": "linux", **state.metrics.sample()})
            if self.path == "/v2/challenge":
                if not state.enable_power:
                    return self.reply({"error": "power control disabled"}, 403)
                if not state.challenge_limits.permit(self.client_address[0]):
                    return self.reply({"error": "challenge rate limit exceeded"}, 429)
                try:
                    nonce = state.nonces.issue()
                except NonceCapacityError:
                    return self.reply({"error": "challenge capacity reached"}, 429)
                return self.reply({"protocol": PROTOCOL, "api_version": API_VERSION,
                                   "id": state.identifier, "platform": "linux",
                                   "nonce": nonce, "expires_in": 30})
            return self.reply({"error": "not found"}, 404)

        def do_POST(self):
            action = self.path.removeprefix("/v2/power/") if self.path.startswith("/v2/power/") else ""
            if action not in ALLOWED_ACTIONS or self.path != f"/v2/power/{action}":
                return self.reply({"error": "not found"}, 404)
            if not state.enable_power:
                return self.reply({"error": "power control disabled"}, 403)
            # Do not accept POST bodies; prevents ambiguity about signed data.
            if self.headers.get("Transfer-Encoding") or self.headers.get("Content-Length", "0") != "0":
                return self.reply({"error": "request body not allowed"}, 400)
            nonce = self.headers.get("X-ComputerHost-Nonce", "")
            provided = self.headers.get("X-ComputerHost-Signature", "")
            if (len(nonce) != 48 or len(provided) != 64 or
                    not all(c in "0123456789abcdefABCDEF" for c in nonce + provided)):
                return self.reply({"error": "unauthorized"}, 401)
            expected = signature(state.secret, self.path, nonce)
            # A bad guess must not consume another client's valid challenge.
            if not hmac.compare_digest(provided.lower(), expected) or not state.nonces.consume(nonce):
                return self.reply({"error": "unauthorized"}, 401)
            try:
                request_power(state.helper_socket, action)
            except (OSError, ValueError, RuntimeError) as exc:
                return self.reply({"error": "power helper unavailable"}, 503)
            return self.reply({"accepted": True, "action": action,
                               "id": state.identifier, "platform": "linux", "protocol": PROTOCOL,
                               "api_version": API_VERSION}, 202)

        def reply(self, obj: dict, code: int = 200):
            encoded = json.dumps(obj, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
            if len(encoded) > MAX_REPLY_BYTES:
                encoded = b'{"error":"response too large"}'
                code = 500
            try:
                self.send_response(code)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(encoded)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("Connection", "close")
                if code == 429:
                    self.send_header("Retry-After", "30")
                self.end_headers()
                self.wfile.write(encoded)
            except (ConnectionError, BrokenPipeError, OSError):
                pass

        def log_message(self, fmt, *args):
            # Never copy attacker-controlled paths or header contents to the journal.
            return

    return Handler


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Linux Host Agent (SmartThings)")
    parser.add_argument("--bind", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--state-dir", type=Path, default=state_dir())
    parser.add_argument("--wol-interface", default=os.environ.get("LINUX_HOST_WOL_INTERFACE") or None)
    parser.add_argument("--temperature-path", default=None)
    parser.add_argument("--enable-power-control", action="store_true", default=False)
    parser.add_argument("--helper-socket", default="/run/linux-host-agent/power.sock")
    opts = parser.parse_args(argv)
    if not 1 <= opts.port <= 65535:
        parser.error("port must be 1..65535")
    identifier = installation_id(opts.state_dir / "installation-id")
    secret = control_secret(opts.state_dir / "control-token")
    state = AgentState(identifier, secret, opts.enable_power_control,
                       opts.helper_socket, opts.wol_interface,
                       opts.temperature_path)
    server = BoundedHTTPServer((opts.bind, opts.port), make_handler(state))
    print(f"Linux Host Agent {VERSION} ID={identifier} listening on {opts.bind}:{opts.port}", flush=True)
    try:
        server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
