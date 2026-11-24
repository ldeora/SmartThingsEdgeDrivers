"""Read-only preflight regression fixtures; never execute system commands."""
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import wol_preflight as gate

IFACE = 'enp1s0f0'
MAC = '02:11:22:33:44:55'
OTHER = '02:11:22:33:44:66'
LOCAL = '/etc/systemd/network/10-wol.link'
NM = ('systemctl', 'show', '--all', '--no-pager',
      '--property=LoadState,ActiveState', '--', 'NetworkManager.service')
UDEV = ('udevadm', 'info', '--query=property', '--path=/sys/class/net/' + IFACE)


class PreflightTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.net = self.root / 'sys/class/net'
        nic = self.net / IFACE
        (nic / 'device').mkdir(parents=True)
        (nic / 'ifindex').write_text('4\n')
        (nic / 'type').write_text('1\n')
        (nic / 'address').write_text(MAC + '\n')
        self.base = self.root / LOCAL.lstrip('/')
        self.base.parent.mkdir(parents=True)
        self.base.write_text('[Match]\nPermanentMACAddress=' + MAC + '\n[Link]\nNamePolicy=keep\n')
        self.dropin = self.base.with_name(self.base.name + '.d')
        self.dropin.mkdir()
        self.replies = {
            ('udevadm', '--version'): '261\n',
            ('systemctl', '--version'): 'systemd 261 (261.2)\n+PAM\n',
            ('ethtool', IFACE): 'Supports Wake-on: pumbg\nWake-on: d\n',
            ('ethtool', '-P', IFACE): 'Permanent address: ' + MAC + '\n',
            NM: 'LoadState=not-found\nActiveState=inactive\n',
            UDEV: 'ID_NET_LINK_FILE=' + LOCAL + '\n',
        }
        self.calls = []

    def run_query(self, args):
        self.calls.append(args)
        answer = self.replies.get(args)
        return answer() if callable(answer) else answer

    def capture(self):
        return gate.capture(IFACE, root=self.root, net=self.net,
                            owner_uid=os.getuid(), run=self.run_query)

    def unchanged(self, approved):
        return gate.unchanged(approved, root=self.root, net=self.net,
                              owner_uid=os.getuid(), run=self.run_query)

    def test_version_gate_accepts_matching_supported_major(self):
        for version in (248, 261):
            self.replies[('udevadm', '--version')] = str(version) + '\n'
            self.replies[('systemctl', '--version')] = f'systemd {version} ({version}.2)\n'
            self.assertEqual(gate.tool_versions(self.run_query).udev, version)

    def test_version_gate_rejects_old_mixed_missing_and_malformed(self):
        for a, b in (('247\n', 'systemd 247\n'),
                     ('261\n', 'systemd 260\n'),
                     (None, 'systemd 261\n'),
                     ('261\n', None), ('261junk\n', 'systemd 261\n'),
                     ('261\n', 'not systemd 261\n'), ('261\n262\n', 'systemd 261\n')):
            with self.subTest(a=a, b=b):
                self.replies[('udevadm', '--version')] = a
                self.replies[('systemctl', '--version')] = b
                self.assertIsNone(self.capture())
        self.assertNotIn(UDEV, self.calls)

    def test_exact_private_snapshot_and_read_only_revalidation(self):
        before = self.base.read_bytes()
        approved = self.capture()
        self.assertIsNotNone(approved)
        self.assertTrue(self.unchanged(approved))
        self.assertNotIn(MAC, repr(approved))
        self.assertNotIn(LOCAL, repr(approved))
        self.assertEqual(self.base.read_bytes(), before)
        self.assertEqual(list(self.dropin.iterdir()), [])

    def test_same_classification_different_base_bytes_requires_new_review(self):
        approved = self.capture()
        self.assertIsNotNone(approved)
        self.base.write_text(self.base.read_text() + '# operator change\n')
        self.assertIsNotNone(self.capture())
        self.assertFalse(self.unchanged(approved))

    def test_earlier_rule_change_or_new_rule_invalidates_snapshot(self):
        earlier = self.base.with_name('05-other.link')
        earlier.write_text('[Match]\nPermanentMACAddress=' + OTHER + '\n')
        approved = self.capture()
        self.assertIsNotNone(approved)
        earlier.write_text(earlier.read_text() + '# changed\n')
        self.assertFalse(self.unchanged(approved))
        earlier.write_text('[Match]\nPermanentMACAddress=' + MAC + '\n')
        self.assertIsNone(self.capture())

    def test_existing_mask_is_bound_to_snapshot(self):
        mask = self.base.with_name('05-masked.link')
        mask.symlink_to('/dev/null')
        approved = self.capture()
        self.assertIsNotNone(approved)
        mask.unlink()
        mask.write_text('')
        self.assertFalse(self.unchanged(approved))

    def test_replaced_empty_directory_requires_new_review(self):
        approved = self.capture()
        self.assertIsNotNone(approved)
        self.dropin.rename(self.dropin.with_name('old-dir'))
        self.dropin.mkdir()
        self.assertIsNotNone(self.capture())
        self.assertFalse(self.unchanged(approved))

    def test_populated_directory_and_explicit_wol_are_not_candidates(self):
        entry = self.dropin / '.hidden'
        entry.write_text('not empty')
        self.assertIsNone(self.capture())
        entry.unlink()
        self.base.write_text(self.base.read_text() + 'WakeOnLan=off\n')
        self.assertIsNone(self.capture())

    def test_nonliteral_and_unknown_selected_settings_refused(self):
        original = self.base.read_text()
        for suffix in ('UnknownSetting=1\n', 'WakeOnLanPassword=secret\n',
                       '[Unknown]\nX=1\n', 'NamePolicy="keep"\n',
                       'NamePolicy=keep\\\n', 'NamePolicy=keep\u2028\n'):
            with self.subTest(suffix=suffix):
                self.base.write_text(original + suffix)
                self.assertIsNone(self.capture())

    def test_missing_directory_and_networkmanager_refused(self):
        self.dropin.rmdir()
        self.assertIsNone(self.capture())
        self.dropin.mkdir()
        self.replies[NM] = 'LoadState=loaded\nActiveState=active\n'
        self.assertIsNone(self.capture())

    def test_nic_change_requires_new_review(self):
        approved = self.capture()
        self.assertIsNotNone(approved)
        (self.net / IFACE / 'ifindex').write_text('5\n')
        self.assertFalse(self.unchanged(approved))

    def test_two_samples_detect_change_between_observations(self):
        original = gate._sample
        count = 0
        def changing(*args):
            nonlocal count
            result = original(*args)
            count += 1
            if count == 1:
                self.base.write_text(self.base.read_text() + '# changed\n')
            return result
        with mock.patch.object(gate, '_sample', side_effect=changing):
            self.assertIsNone(self.capture())
        self.assertEqual(count, 2)

    def test_invalid_interface_and_untrusted_approval_never_query(self):
        self.assertIsNone(gate.capture('../private', run=self.run_query))
        self.assertFalse(gate.unchanged({'interface': IFACE}, run=self.run_query))
        self.assertEqual(self.calls, [])

    def test_rule_hardlink_refused(self):
        os.link(self.base, self.root / 'other')
        self.assertIsNone(self.capture())


if __name__ == '__main__':
    unittest.main()
