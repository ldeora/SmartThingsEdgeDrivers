"""Exercise actual nmcli read and numeric write-back, with an inactive
synthetic profile. Run ONLY in the disposable CI NetworkManager container."""
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from persistent_wol import Backend, parse_nm_value

PROPERTY = "802-3-ethernet.wake-on-lan"
PROFILE = str(uuid.uuid4())


def nm(*args):
    return subprocess.check_output(["nmcli", "--wait", "5", *args],
                                   text=True, timeout=15,
                                   env={**os.environ, "LC_ALL": "C"}).strip()


if os.environ.get("COMPUTER_HOST_NMCLI_CONTAINER") != "1":
    raise SystemExit("Refusing to run outside disposable NetworkManager smoke container")
for _ in range(30):
    try:
        nm("-g", "RUNNING", "general")
        break
    except (subprocess.SubprocessError, OSError):
        time.sleep(1)
else:
    raise SystemExit("NetworkManager did not become available")

print(nm("--version"), flush=True)
nm("connection", "add", "type", "ethernet", "ifname", "woltest0",
   "con-name", "computer-host-wol-ci", "connection.uuid", PROFILE,
   "connection.autoconnect", "no")
try:
    backend = Backend()
    for setting, expected in (("default", "1"), ("magic", "64"),
                              ("66", "66"), ("ignore", "32768"), ("0", "0")):
        nm("connection", "modify", "uuid", PROFILE, PROPERTY, setting)
        raw = nm("-g", PROPERTY, "connection", "show", "uuid", PROFILE)
        print(f"nmcli {setting}: {raw!r}", flush=True)
        previous = backend._nm_value(PROFILE)
        assert parse_nm_value(raw) == previous == expected, (raw, previous, expected)
        nm("connection", "modify", "uuid", PROFILE, PROPERTY, "magic")
        assert backend._nm_value(PROFILE) == "64"
        nm("connection", "modify", "uuid", PROFILE, PROPERTY, previous)
        assert backend._nm_value(PROFILE) == expected
finally:
    nm("connection", "delete", "uuid", PROFILE)
print("PASS: real nmcli WOL read/modify/restore, no profile activation", flush=True)
