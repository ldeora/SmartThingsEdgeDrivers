"""Disposable, read-only Computer Host endpoint for physical-hub testing.

Never run as root. This is a synthetic test fixture, not the agent.
"""
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import ipaddress
import json
from pathlib import Path
import select
import time
import uuid

MODES = ("normal", "drip-header", "drip-body", "stall-body")


def private_ipv4(value):
    address = ipaddress.IPv4Address(value)
    if not address.is_private or address.is_unspecified or address.is_multicast:
        raise argparse.ArgumentTypeError("specify a private unicast IPv4 address")
    return str(address)


class Server(ThreadingHTTPServer):
    daemon_threads = True

    def verify_request(self, request, client_address):
        return client_address[0] == self.allowed_peer

    def get_request(self):
        conn, address = super().get_request()
        conn.settimeout(4)
        return conn, address


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass  # Never log request headers or untrusted request paths.

    def do_POST(self):
        self.send_error(403, "Monitoring-only test fixture")

    def do_GET(self):
        common = dict(protocol="computer-host-agent", api_version=2, platform="linux",
                      id=self.server.installation)
        if self.path == "/v2/info":
            body = dict(common, hostname="HTTP Deadline Test Fixture",
                        agent_version="0.0.0-test", features=["health", "metrics"],
                        power_actions=[])
        elif self.path == "/v2/health":
            body = dict(common, status="running", boot_id=self.server.boot_id,
                        uptime_seconds=time.monotonic() - self.server.started)
        elif self.path == "/v2/metrics":
            body = dict(common, cpu_usage_percent=12.5, memory_usage_percent=25,
                        cpu_temperature_c=42, uptime_seconds=time.monotonic() - self.server.started,
                        boot_id=self.server.boot_id)
        else:
            self.send_error(403, "Monitoring-only test fixture")
            return
        mode = self.server.mode_file.read_text().strip() if self.path == "/v2/health" else "normal"
        if mode not in MODES:
            self.send_error(400, "Invalid fixture mode")
            return
        encoded = json.dumps(body).encode("ascii")
        header = (b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n"
                  + b"Content-Length: " + str(len(encoded)).encode()
                  + b"\r\nConnection: close\r\n")
        self.close_connection = True
        start = time.monotonic()
        try:
            if mode == "normal":
                self.connection.sendall(header + b"\r\n" + encoded)
                return
            if mode == "drip-header":
                self.connection.sendall(header + b"X-Slow: ")
            else:
                self.connection.sendall(header + b"\r\n" + encoded[:1])
            # Never let the probe itself retain a slow test connection forever.
            end = start + 12
            while time.monotonic() < end:
                readable, _, _ = select.select([self.connection], [], [], 0.25)
                if readable and not self.connection.recv(1):
                    print(f"{mode}: peer closed after {time.monotonic()-start:.3f}s", flush=True)
                    return
                if mode != "stall-body":
                    self.connection.sendall(b"x")
            print(f"{mode}: probe-side 12s limit reached (NOT client deadline)", flush=True)
        except (BrokenPipeError, ConnectionResetError):
            print(f"{mode}: peer closed/reset after {time.monotonic()-start:.3f}s", flush=True)
        except OSError as exc:
            print(f"{mode}: socket error {type(exc).__name__} after {time.monotonic()-start:.3f}s", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bind", required=True, type=private_ipv4)
    parser.add_argument("--allow-peer", required=True, type=private_ipv4)
    parser.add_argument("--port", type=int, default=18765)
    parser.add_argument("--mode-file", required=True, type=Path)
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error("use a non-privileged port")
    if args.mode_file.read_text().strip() not in MODES:
        parser.error("mode file must contain one of: " + ", ".join(MODES))
    with Server((args.bind, args.port), Handler) as server:
        server.allowed_peer = args.allow_peer
        server.mode_file = args.mode_file
        server.installation = str(uuid.uuid4())
        server.boot_id = str(uuid.uuid4())
        server.started = time.monotonic()
        print(f"Read-only test fixture on {args.bind}:{args.port}, peer {args.allow_peer}", flush=True)
        print("Random test identity, no real host credentials or WOL metadata. Ctrl-C stops.", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
