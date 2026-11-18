#!/usr/bin/env python3
"""Linux Host Agent 0.3.0: bounded read-mostly HTTP endpoint for SmartThings.

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
VERSION = "0.4.1-beta.1"
API_VERSION = 2
ALLOWED_ACTIONS = frozenset(("shutdown", "reboot", "suspend"))
MAX_REPLY_BYTES = 32 * 1024
CLIENT_IO_TIMEOUT_SECONDS = 4.0
MAX_CONCURRENT_CLIENTS = 12
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
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        fd = None
    if fd is not None:
        with os.fdopen(fd, "w", encoding="ascii") as out:
            out.write(create() + "\n")
            out.flush()
            os.fsync(out.fileno())
    try:
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


def memory_metrics(raw: str | None) -> tuple[int | None, float | None]:
    vals = {}
    if raw:
        for line in raw.splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                try:
                    vals[k] = int(v.split()[0]) * 1024
                except (ValueError, IndexError):
                    continue
    total = vals.get("MemTotal")
    free = vals.get("MemAvailable")
    if not total or free is None:
        return None, None
    return total, round(100 * (total - free) / total, 1)


def disk_metrics(path: str = "/") -> tuple[float | None, int | None]:
    """Return root filesystem usage and logical total capacity from one statvfs call.

    f_blocks includes the total filesystem blocks; f_bavail measures space
    available to unprivileged users, preserving existing usage semantics.
    """
    try:
        s = os.statvfs(path)
        total = s.f_blocks * s.f_frsize
        if total <= 0:
            return None, None
        available = s.f_bavail * s.f_frsize
        used_percent = round(100 * (total - available) / total, 1)
        return used_percent, total
    except OSError:
        return None, None


def disk_used_percent(path: str = "/") -> float | None:
    """Backwards-compatible percentage helper."""
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
        total_mem, memory_percent = memory_metrics(read_first("/proc/meminfo"))
        disk_percent, disk_total = disk_metrics()
        temp, temp_label = choose_temperature(self.temperature_path)
        try:
            loads = [round(x, 2) for x in os.getloadavg()]
        except OSError:
            loads = [None, None, None]
        return {
            "cpu_usage_percent": cpu_percent,
            "memory_usage_percent": memory_percent,
            "memory_total_bytes": total_mem,
            "cpu_temperature_c": temp,
            "cpu_temperature_label": temp_label,
            "disk_root_usage_percent": disk_percent,
            "disk_root_total_bytes": disk_total,
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
    """Enforce a cumulative byte/time budget while HTTP headers are parsed.

    Every request uses HTTP/1.0 / Connection: close and has no body. A slow
    client cannot bypass the deadline by drip-feeding bytes before each socket
    inactivity timeout. Exceeding either budget closes only that connection.
    """
    def __init__(self, reader, conn: socket.socket, *, io_timeout: float,
                 max_bytes: int = MAX_HTTP_HEADER_BYTES,
                 deadline_seconds: float = MAX_HTTP_HEADER_SECONDS):
        self.reader = reader
        self.conn = conn
        self.io_timeout = io_timeout
        self.max_bytes = max_bytes
        self.used = 0
        self.deadline = time.monotonic() + deadline_seconds

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

    Excess clients are closed by the accept loop *without* spawning threads;
    local hub retries can then recover when capacity becomes available.
    """
    daemon_threads = True
    block_on_close = False
    request_queue_size = 16
    allow_reuse_address = True

    def __init__(self, server_address, request_handler_class,
                 max_clients: int = MAX_CONCURRENT_CLIENTS,
                 io_timeout: float = CLIENT_IO_TIMEOUT_SECONDS):
        self._slots = threading.BoundedSemaphore(max_clients)
        self.io_timeout = io_timeout
        super().__init__(server_address, request_handler_class)

    def get_request(self):
        sock, addr = super().get_request()
        sock.settimeout(self.io_timeout)
        return sock, addr

    def process_request(self, request, client_address):
        if not self._slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self._slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._slots.release()


def signature(secret_hex: str, path: str, nonce: str) -> str:
    data = f"POST\n{path}\n{nonce}\n".encode("ascii")
    return hmac.new(bytes.fromhex(secret_hex), data, hashlib.sha256).hexdigest()


def request_power(sockpath: str, action: str, timeout: float = 2) -> None:
    if action not in ALLOWED_ACTIONS:
        raise ValueError("invalid action")
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
        s.settimeout(timeout)
        s.connect(sockpath)
        s.sendall((action + "\n").encode("ascii"))
        response = s.recv(128)
    if response != b"OK\n":
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
        server_version = "LinuxHostAgent/0.3.0"
        sys_version = ""

        def setup(self):
            super().setup()
            self.rfile = HeaderBudgetReader(self.rfile, self.connection,
                                            io_timeout=getattr(self.server, "io_timeout", CLIENT_IO_TIMEOUT_SECONDS))

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
