"""Fake-command tests only: no system network mutation."""
import os
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from persistent_wol import Backend, WolError

NIC = "enp1s0"
MAC = "02:11:22:33:44:55"
PROFILE = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"


class WolTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.nic = self.root / "sys/class/net" / NIC
        (self.nic / "device").mkdir(parents=True)
        for name, value in (("type", "1"), ("address", MAC), ("ifindex", "4"),
                            ("uevent", "INTERFACE=" + NIC)):
            (self.nic / name).write_text(value + "\n")
        self.default = self.root / "usr/lib/systemd/network/99-default.link"
        self.default.parent.mkdir(parents=True)
        self.default.write_text("[Match]\nOriginalName=*\n[Link]\nNamePolicy=keep\n")
        self.selected = "/usr/lib/systemd/network/99-default.link"
        self.runtime = "d"
        self.supported = "pumbg"
        self.nm = False
        self.value = "1"
        self.writes = []
        self.backend = Backend(root=self.root, run=self.run_fake, owner_uid=os.getuid())

    def run_fake(self, args):
        if args[0] == "ethtool":
            if args[1] == "-s":
                self.writes.append(args)
                self.runtime = args[-1]
                return ""
            return "Supports Wake-on: " + self.supported + "\nWake-on: " + self.runtime + "\n"
        if args[0] == "systemctl":
            return "LoadState=loaded\nActiveState=" + ("active" if self.nm else "inactive") + "\n"
        if args[0] == "udevadm":
            return "ID_NET_LINK_FILE=" + self.selected + "\n"
        if args[0] == "nmcli":
            if "modify" in args:
                self.writes.append(args)
                self.value = "64" if args[-1] == "magic" else args[-1]
                return ""
            if "GENERAL.CON-UUID" in args:
                return PROFILE
            return self.value + "\n"
        raise AssertionError(args)

    def test_link_apply_restore(self):
        plan = self.backend.inspect(NIC)
        self.assertTrue(plan.owns_change)
        target = self.root / "etc/systemd/network" / plan.link_name
        self.assertFalse(target.exists())
        self.backend.apply(plan)
        self.assertEqual(target.read_text(), self.backend.link_content(MAC))
        self.assertEqual(self.runtime, "g")
        self.backend.restore(plan)
        self.backend.restore(plan)
        self.assertFalse(target.exists())
        self.assertEqual(self.runtime, "d")

    def test_matching_existing_rule_not_owned(self):
        target = self.root / "etc/systemd/network/10-wol.link"
        target.parent.mkdir(parents=True)
        target.write_text(self.backend.link_content(MAC))
        self.selected = "/etc/systemd/network/10-wol.link"
        plan = self.backend.inspect(NIC)
        self.assertFalse(plan.owns_change)
        self.backend.apply(plan)
        self.backend.restore(plan)
        self.assertTrue(target.exists())

    def test_no_clobber(self):
        plan = self.backend.inspect(NIC)
        target = self.root / "etc/systemd/network" / plan.link_name
        target.parent.mkdir(parents=True)
        target.write_text("administrator configuration")
        with self.assertRaises(WolError):
            self.backend.apply(plan)
        self.assertEqual(target.read_text(), "administrator configuration")
        self.assertEqual(self.writes, [])

    def test_conflict_after_apply(self):
        plan = self.backend.inspect(NIC)
        self.backend.apply(plan)
        target = self.root / "etc/systemd/network" / plan.link_name
        target.write_text("administrator changed configuration")
        with self.assertRaises(WolError):
            self.backend.restore(plan)
        self.assertEqual(target.read_text(), "administrator changed configuration")

    def test_networkmanager_apply_restore(self):
        self.nm = True
        plan = self.backend.inspect(NIC)
        self.assertTrue(plan.owns_change)
        self.backend.apply(plan)
        self.assertEqual(self.value, "64")
        self.assertEqual(self.runtime, "g")
        self.backend.restore(plan)
        self.backend.restore(plan)
        self.assertEqual(self.value, "1")
        self.assertEqual(self.runtime, "d")

    def test_nm_existing_magic_not_owned(self):
        self.nm = True
        self.value = "64"
        plan = self.backend.inspect(NIC)
        self.assertFalse(plan.owns_change)
        self.backend.apply(plan)
        self.backend.restore(plan)
        self.assertFalse(any("nmcli" in args for args in self.writes))

    def test_wifi_and_unsupported(self):
        self.supported = "p"
        with self.assertRaisesRegex(WolError, "unsupported"):
            self.backend.inspect(NIC)
        self.supported = "pumbg"
        (self.nic / "wireless").mkdir()
        with self.assertRaisesRegex(WolError, "wired"):
            self.backend.inspect(NIC)
        self.assertEqual(self.writes, [])

    def test_runtime_conflict(self):
        self.nm = True
        plan = self.backend.inspect(NIC)
        self.backend.apply(plan)
        self.runtime = "p"
        with self.assertRaisesRegex(WolError, "externally"):
            self.backend.restore(plan)
        self.assertEqual(self.value, "64")


if __name__ == "__main__":
    unittest.main()
