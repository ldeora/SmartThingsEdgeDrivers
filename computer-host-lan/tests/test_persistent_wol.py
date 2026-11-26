"""Fake-command tests only: no system network mutation."""
import os
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from persistent_wol import Backend, WolError, parse_nm_value
from wol_ownership import Ownership, plan_digest

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
        self.default.write_text("[Match]\nOriginalName=*\n[Link]\nNamePolicy=keep\n"
                                "AlternativeNamesPolicy=database onboard slot path\n"
                                "MACAddressPolicy=persistent\nWakeOnLan=off\n")
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
            if "connection.id" in args:
                return "Wired connection 1\n"
            return self.value + "\n"
        raise AssertionError(args)

    def owned(self):
        boot = self.root / "proc/sys/kernel/random/boot_id"
        boot.parent.mkdir(parents=True, exist_ok=True)
        boot.write_text("aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee\n")
        (self.root / "var/lib/linux-host-agent-installer").mkdir(parents=True, exist_ok=True)
        return Ownership(root=self.root, owner_uid=os.getuid(), backend=self.backend)

    def test_protected_link_ownership_and_rollback(self):
        owned = self.owned()
        plan = self.backend.inspect(NIC)
        intent = owned.prepare(NIC, plan_digest(plan), "test-transaction")
        self.assertIsNone(owned._read(plan))
        owned.apply(intent, "test-transaction")
        target = self.root / "etc/systemd/network" / plan.link_name
        self.assertEqual(owned._read(plan)["state"], "confirmed")
        self.assertEqual(owned._read(plan)["inode"], target.stat().st_ino)
        owned.rollback(intent, "test-transaction")
        self.assertFalse(target.exists())
        self.assertIsNone(owned._read(plan))
        owned.rollback(intent, "test-transaction")
        self.assertEqual(self.runtime, "d")

    def test_protected_collision_never_removed(self):
        owned = self.owned()
        plan = self.backend.inspect(NIC)
        intent = owned.prepare(NIC, plan_digest(plan), "test-transaction")
        target = self.root / "etc/systemd/network" / plan.link_name
        target.parent.mkdir(parents=True)
        target.write_text(plan.link_text)
        with self.assertRaises(WolError):
            owned.apply(intent, "test-transaction")
        owned.rollback(intent, "test-transaction")
        self.assertEqual(target.read_text(), plan.link_text)
        self.assertIsNone(owned._read(plan))

    def test_protected_identical_replacement_after_publication_not_owned(self):
        owned = self.owned()
        plan = self.backend.inspect(NIC)
        intent = owned.prepare(NIC, plan_digest(plan), "test-transaction")
        target = self.root / "etc/systemd/network" / plan.link_name
        create = self.backend._create

        def replace_after_publication(value):
            published = create(value)
            other = target.with_suffix(".admin")
            other.write_text(plan.link_text)
            os.replace(other, target)
            return published

        self.backend._create = replace_after_publication
        with self.assertRaisesRegex(WolError, "changed before confirmation"):
            owned.apply(intent, "test-transaction")
        with self.assertRaisesRegex(WolError, "unconfirmed"):
            owned.rollback(intent, "test-transaction")
        self.assertEqual(target.read_text(), plan.link_text)
        self.assertEqual(owned._read(plan)["state"], "pending")

    def test_protected_nm_keeps_original_baseline(self):
        owned = self.owned()
        self.nm = True
        self.value = "1"
        plan = self.backend.inspect(NIC)
        intent = owned.prepare(NIC, plan_digest(plan), "first")
        owned.apply(intent, "first")
        original = owned._read(plan)
        second = self.backend.inspect(NIC)
        self.assertIsNone(owned.prepare(NIC, plan_digest(second), "second"))
        self.assertEqual(owned._read(plan), original)
        owned.rollback(intent, "first")
        self.assertEqual(self.value, "1")
        self.assertEqual(self.runtime, "d")

    def test_protected_nm_failure_after_persistent_write_rolls_back(self):
        owned = self.owned()
        self.nm = True
        plan = self.backend.inspect(NIC)
        intent = owned.prepare(NIC, plan_digest(plan), "first")
        run = self.backend.run

        def fail_runtime(args):
            if args[:2] == ("ethtool", "-s"):
                raise WolError("runtime write failed")
            return run(args)

        self.backend.run = fail_runtime
        with self.assertRaisesRegex(WolError, "runtime write failed"):
            owned.apply(intent, "first")
        self.assertEqual(self.value, "64")
        self.assertEqual(owned._read(plan)["state"], "confirmed")
        self.backend.run = run
        owned.rollback(intent, "first")
        self.assertEqual(self.value, "1")
        self.assertIsNone(owned._read(plan))

    def test_protected_rejects_changed_plan_digest(self):
        owned = self.owned()
        plan = self.backend.inspect(NIC)
        self.default.write_text(self.default.read_text() + "MTUBytes=1500\n")
        with self.assertRaisesRegex(WolError, "plan changed"):
            owned.prepare(NIC, plan_digest(plan), "first")
        self.assertEqual(self.writes, [])

    def test_visible_policy_digest_ignores_runtime_but_not_policy(self):
        from dataclasses import replace
        from persistent_wol import policy_digest
        plan = self.backend.inspect(NIC)
        different = replace(plan, adapter=replace(plan.adapter, runtime="g", supported="",
                                                  ifindex=100))
        self.assertEqual(policy_digest(plan), policy_digest(different))
        self.assertNotEqual(policy_digest(plan),
                            policy_digest(replace(plan, link_text=plan.link_text + "# edit")))

    def test_preview_unknown_ethtool_capability(self):
        from persistent_wol import preview_policy
        run = self.backend.run

        def denied(args):
            if args[0] == "ethtool":
                raise WolError("permission denied")
            return run(args)

        plan = self.backend.inspect(NIC)
        self.backend.run = denied
        result = preview_policy(NIC, backend=self.backend)
        self.assertEqual(result["capability"], "unknown")
        self.assertEqual(result["digest"], plan_digest(plan))
        self.backend.run = run

    def test_unsupported_adapter_is_distinct_from_unknown(self):
        from persistent_wol import WolUnsupported, preview_policy
        self.nm = True
        self.supported = "d"
        preview = preview_policy(NIC, backend=self.backend)
        self.assertEqual(preview["capability"], "unsupported")
        self.assertEqual(preview["connection_name"], "Wired connection 1")
        with self.assertRaises(WolUnsupported):
            self.backend.inspect(NIC)
        self.assertEqual(self.writes, [])

    def test_missing_ethtool_is_capability_unknown_not_policy_conflict(self):
        from persistent_wol import WolCapabilityUnknown, preview_policy
        run = self.backend.run

        def missing(args):
            if args[0] == "ethtool":
                raise WolError("command failed")
            return run(args)

        self.backend.run = missing
        self.assertEqual(preview_policy(NIC, backend=self.backend)["capability"], "unknown")
        with self.assertRaises(WolCapabilityUnknown):
            self.backend.inspect(NIC)
        self.assertEqual(self.writes, [])

    def test_explicit_owned_nm_removal_preserves_original_policy(self):
        owned = self.owned()
        self.nm = True
        plan = self.backend.inspect(NIC)
        self.assertEqual(owned.inspect_owned(NIC), "not_managed")
        intent = owned.prepare(NIC, plan_digest(plan), "first")
        owned.apply(intent, "first")
        self.assertEqual(owned.inspect_owned(NIC), "managed")
        self.assertEqual(owned.remove_owned(NIC), "removed")
        self.assertEqual(self.value, "1")
        self.assertEqual(owned.remove_owned(NIC), "not_managed")

    def test_link_apply_restore(self):
        plan = self.backend.inspect(NIC)
        self.assertTrue(plan.owns_change)
        target = self.root / "etc/systemd/network" / plan.link_name
        self.assertFalse(target.exists())
        self.backend.apply(plan)
        self.assertEqual(target.read_text(), plan.link_text)
        self.assertIn("AlternativeNamesPolicy=database onboard slot path", plan.link_text)
        self.assertIn("MACAddressPolicy=persistent", plan.link_text)
        self.assertNotIn("WakeOnLan=off", plan.link_text)
        self.assertEqual(plan.link_text.count("WakeOnLan="), 1)
        self.assertEqual(self.runtime, "g")
        self.backend.restore(plan)
        self.backend.restore(plan)
        self.assertFalse(target.exists())
        self.assertEqual(self.runtime, "d")

    def test_matching_existing_rule_not_owned(self):
        target = self.root / "etc/systemd/network/10-wol.link"
        target.parent.mkdir(parents=True)
        target.write_text(self.backend.link_content(MAC, self.default.read_text()))
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

    def test_nm_parser_forms(self):
        for raw, expected in (("default", "1"), ("1 (default)", "1"),
                              ("magic", "64"), ("64 (magic)", "64"),
                              ("phy, magic", "66"), ("66 (phy, magic)", "66"),
                              ("0x42", "66"), ("ignore", "32768"),
                              ("none", "0"), ("0", "0"), ("", "0"), ("all", "126")):
            with self.subTest(raw=raw):
                self.assertEqual(parse_nm_value(raw), expected)
        for raw in ("unknown", "default,magic", "ignore,magic",
                    "none,magic", "129", "65", "-1", "0x10000"):
            with self.subTest(raw=raw), self.assertRaises(WolError):
                parse_nm_value(raw)

    def test_nm_zero_flags_roundtrip(self):
        self.nm = True
        self.value = ""
        plan = self.backend.inspect(NIC)
        self.assertEqual(plan.previous, "0")
        self.backend.apply(plan)
        self.assertEqual(self.value, "64")
        self.backend.restore(plan)
        self.assertEqual(self.value, "0")
        self.assertEqual(self.runtime, "d")

    def test_failed_nm_query_not_zero(self):
        self.nm = True
        original = self.backend.run

        def failed_query(args):
            if "802-3-ethernet.wake-on-lan" in args:
                raise WolError("WOL command failed")
            return original(args)

        self.backend.run = failed_query
        with self.assertRaisesRegex(WolError, "command failed"):
            self.backend.inspect(NIC)
        self.assertEqual(self.writes, [])

    def test_existing_magic_flags_and_runtime_preserved(self):
        self.nm = True
        self.value = "66 (phy, magic)"
        self.runtime = "pg"
        plan = self.backend.inspect(NIC)
        self.assertFalse(plan.owns_change)
        self.backend.apply(plan)
        self.backend.restore(plan)
        self.assertEqual(self.value, "66 (phy, magic)")
        self.assertEqual(self.runtime, "pg")
        self.assertEqual(self.writes, [])

    def test_existing_magic_flags_runtime_only_change(self):
        self.nm = True
        self.value = "66"
        plan = self.backend.inspect(NIC)
        self.backend.apply(plan)
        self.assertEqual(self.value, "66")
        self.assertEqual(self.runtime, "g")
        self.backend.restore(plan)
        self.assertEqual(self.runtime, "d")
        self.assertEqual(self.value, "66")
        self.assertFalse(any("nmcli" in args for args in self.writes))

    def test_link_runtime_already_magic(self):
        self.runtime = "pg"
        plan = self.backend.inspect(NIC)
        self.backend.apply(plan)
        self.backend.restore(plan)
        self.assertEqual(self.runtime, "pg")
        self.assertEqual(self.writes, [])

    def test_default_rule_changes_before_apply(self):
        plan = self.backend.inspect(NIC)
        self.default.write_text(self.default.read_text() + "MTUBytes=1500\n")
        with self.assertRaisesRegex(WolError, "plan changed"):
            self.backend.apply(plan)
        self.assertEqual(self.writes, [])
        self.assertFalse((self.root / "etc/systemd/network" / plan.link_name).exists())

    def test_custom_link_refusal_guidance(self):
        target = self.root / "etc/systemd/network/10-netplan-eth.link"
        target.parent.mkdir(parents=True)
        target.write_text("[Match]\nOriginalName=enp1s0\n[Link]\nMTUBytes=1500\n")
        self.selected = "/etc/systemd/network/10-netplan-eth.link"
        with self.assertRaisesRegex(WolError, r"10-netplan-eth\.link.*WakeOnLan=magic"):
            self.backend.inspect(NIC)
        self.assertEqual(self.writes, [])

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
