"""Fixture-only WOL inspector tests; no live NIC or network mutation."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import wol_inspect as wol

IFACE = 'enp1s0f0'
MAC = '02:11:22:33:44:55'
UUID = 'b9024f22-4e09-4413-9c36-3d7b75563051'
NM_STATE = ('systemctl', 'show', '--all', '--no-pager',
            '--property=LoadState,ActiveState', '--', 'NetworkManager.service')
NM_UUID = ('nmcli', '--wait', '5', '--get-values',
           'GENERAL.CON-UUID', 'device', 'show', IFACE)
NM_POLICY = ('nmcli', '--wait', '5', '--get-values',
             '802-3-ethernet.wake-on-lan', 'connection', 'show', 'uuid', UUID)
UDEV = ('udevadm', 'info', '--query=property', '--path=/sys/class/net/' + IFACE)
WOL = ('ethtool', IFACE)
IOCTL = ('ethtool', '--disable-netlink', IFACE)
PERM = ('ethtool', '-P', IFACE)
HARDWARE = 'Supports Wake-on: pumbg\nWake-on: g\n'
ACTIVE = 'LoadState=loaded\nActiveState=active\n'
INACTIVE = 'LoadState=not-found\nActiveState=inactive\n'


class WolInspectionTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.net = Path(temp.name)
        self.nic = self.net / IFACE
        self.nic.mkdir()
        (self.nic / 'ifindex').write_text('4\n')
        (self.nic / 'address').write_text(MAC + '\n')
        (self.nic / 'type').write_text('1\n')
        (self.nic / 'device').mkdir()
        self.replies = {WOL: HARDWARE, PERM: 'Permanent address: ' + MAC + '\n',
                        NM_STATE: INACTIVE,
                        UDEV: 'ID_NET_LINK_FILE=/etc/systemd/network/10-wol.link\n'}
        self.calls = []
        self.link = '[Match]\nMACAddress=' + MAC + '\n[Link]\nWakeOnLan=magic\n'

    def run_query(self, args):
        self.calls.append(args)
        if args not in self.replies:
            return None
        value = self.replies[args]
        return value() if callable(value) else value

    def inspect(self, interface=IFACE):
        return wol.inspect(interface, net=self.net, run=self.run_query,
                           link_reader=lambda path: self.link)

    def test_observed_local_link_never_claims_persistence(self):
        self.link += 'WakeOnLanPassword=DO-NOT-EMIT\n'
        result = self.inspect()
        self.assertEqual(result['backend'], 'systemd_udev')
        self.assertEqual(result['observed_link'], 'local')
        self.assertEqual(result['base_link_policy'], 'magic_declared')
        self.assertEqual(result['magic_packet_support'], 'supported')
        self.assertEqual(result['runtime_magic_packet'], 'enabled')
        self.assertEqual(result['permanent_mac_match'], 'matches')
        self.assertFalse(result['persistence_verified'])
        self.assertFalse(result['changes_applied'])
        self.assertFalse(result['secrets_included'])
        wire = json.dumps(result)
        for value in (MAC, IFACE, '10-wol.link', 'DO-NOT-EMIT'):
            self.assertNotIn(value, wire)
        self.assertEqual(self.calls, [WOL, PERM, NM_STATE, UDEV])

    def test_incomplete_netlink_output_uses_legacy_ioctl(self):
        self.replies[WOL] = 'Supports Wake-on: pumbg\n'
        self.replies[IOCTL] = 'Supports Wake-on: pumbg\nWake-on: d\n'
        result = self.inspect()
        self.assertEqual(result['hardware_query'], 'ioctl')
        self.assertEqual(result['runtime_magic_packet'], 'disabled')

    def test_unreadable_is_not_unsupported(self):
        self.replies[WOL] = None
        result = self.inspect()
        self.assertEqual(result['magic_packet_support'], 'not_verified')
        self.assertEqual(result['runtime_magic_packet'], 'not_verified')
        self.assertIn(IOCTL, self.calls)

    def test_actual_unsupported_magic_is_distinguished(self):
        self.replies[WOL] = 'Supports Wake-on: p\nWake-on: d\n'
        self.assertEqual(self.inspect()['magic_packet_support'], 'unsupported')

    def test_nm_profile_flags_and_redaction(self):
        self.replies.update({NM_STATE: ACTIVE, NM_UUID: UUID + '\n',
                             NM_POLICY: '66 (phy, magic)\n'})
        result = self.inspect()
        self.assertEqual(result['backend'], 'networkmanager')
        self.assertEqual(result['nm_profile_policy'], 'magic_with_other_flags')
        self.assertEqual(result['observed_link'], 'not_verified')
        self.assertNotIn(UDEV, self.calls)
        self.assertNotIn(UUID, json.dumps(result))

    def test_active_nm_without_profile_never_falls_back_to_udev(self):
        self.replies.update({NM_STATE: ACTIVE, NM_UUID: '--\n'})
        result = self.inspect()
        self.assertEqual(result['backend'], 'not_verified')
        self.assertNotIn(UDEV, self.calls)
        self.assertNotIn(NM_POLICY, self.calls)

    def test_manager_query_failure_never_falls_back(self):
        for output in (None, 'LoadState=loaded\n', 'LoadState=loaded\nActiveState=activating\n'):
            with self.subTest(output=output):
                self.calls.clear()
                self.replies[NM_STATE] = output
                self.assertEqual(self.inspect()['backend'], 'not_verified')
                self.assertNotIn(UDEV, self.calls)

    def test_nm_profile_changed_during_read(self):
        values = iter((UUID, 'aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee'))
        self.replies.update({NM_STATE: ACTIVE, NM_UUID: lambda: next(values),
                             NM_POLICY: 'magic'})
        result = self.inspect()
        self.assertEqual(result['backend'], 'not_verified')
        self.assertEqual(result['nm_profile_policy'], 'not_verified')

    def test_interface_changed_invalidates_observations(self):
        def move():
            (self.nic / 'ifindex').write_text('5')
            return HARDWARE

        self.replies[WOL] = move
        result = self.inspect()
        self.assertEqual(result['interface_state'], 'interface_changed')
        self.assertEqual(result['magic_packet_support'], 'not_verified')
        self.assertEqual(result['backend'], 'not_verified')

    def test_permanent_address_differs(self):
        self.replies[PERM] = 'Permanent address: 02:ab:cd:ef:11:22\n'
        self.assertEqual(self.inspect()['permanent_mac_match'], 'differs')

    def test_invalid_names_never_run_commands(self):
        for name in ('.', '..', '-eth0', 'eth0;id', 'eth0/other', 'a' * 16):
            with self.subTest(name=name):
                self.assertEqual(self.inspect(name)['interface_state'], 'invalid_interface')
        self.assertEqual(self.calls, [])

    def test_wireless_and_virtual_devices_are_not_candidates(self):
        (self.nic / 'wireless').mkdir()
        self.assertEqual(self.inspect()['interface_state'], 'unsupported_interface')
        (self.nic / 'wireless').rmdir()
        (self.nic / 'device').rmdir()
        self.assertEqual(self.inspect()['interface_state'], 'unsupported_interface')
        self.assertEqual(self.calls, [])

    def test_unknown_or_untrusted_observed_link_never_read(self):
        for value in ('/tmp/private.link', '/etc/systemd/network/../private.link',
                      '/etc/systemd/network/a.link\nID_NET_LINK_FILE=/etc/systemd/network/b.link'):
            self.replies[UDEV] = 'ID_NET_LINK_FILE=' + value + '\n'
            with mock.patch.object(wol, 'base_link_policy') as parse:
                self.assertEqual(self.inspect()['backend'], 'not_verified')
                parse.assert_not_called()

    def test_ethtool_parser_rejects_inconsistent_or_duplicate_values(self):
        for value in ('Supports Wake-on: p\nWake-on: g\n',
                      'Supports Wake-on: g\nWake-on: gg\n',
                      HARDWARE + 'Wake-on: d\n',
                      'Supports Wake-on: dg\nWake-on: d\n'):
            self.assertIsNone(wol.parse_ethtool(value))

    def test_nm_policy_preserves_special_and_combined_flags(self):
        for value, expected in (
                ('1 (default)', 'default'), ('0x8000', 'ignore'),
                ('0 (none)', 'none'), ('magic', 'magic'),
                ('64 (magic)', 'magic'), ('66', 'magic_with_other_flags'),
                ('2 (phy)', 'other_flags'), ('65', 'not_verified'),
                ('32769', 'not_verified'), ('--', 'not_verified')):
            with self.subTest(value=value):
                self.assertEqual(wol.parse_nm_policy(value), expected)

    def test_base_link_parser_is_conservative(self):
        for value, expected in (
                ('[Link]\nWakeOnLan=magic\n', 'magic_declared'),
                ('[Link]\nWakeOnLan=off\n', 'other_declared'),
                ('[Link]\nNamePolicy=keep\n', 'unspecified'),
                ('[Match]\nWakeOnLan=magic\n[Link]\nNamePolicy=keep\n', 'unspecified'),
                ('[Link]\nWakeOnLan=magic\nWakeOnLan=off\n', 'not_verified'),
                ('[Link]\nWakeOnLan=magic\n[Link]\n', 'not_verified'),
                ('[Link]\nWakeOnLan=magic\\\n off\n', 'not_verified')):
            with self.subTest(value=value):
                self.assertEqual(wol.base_link_policy(value), expected)

    def test_query_errors_do_not_return_partial_output(self):
        with mock.patch.object(wol.shutil, 'which', return_value='/usr/sbin/ethtool'):
            for result in (
                    subprocess.CompletedProcess([], 1, stdout=HARDWARE.encode()),
                    subprocess.CompletedProcess([], 0, stdout=b'x' * 65537),
                    subprocess.CompletedProcess([], 0, stdout=b'\xff')):
                with mock.patch.object(wol.subprocess, 'run', return_value=result):
                    self.assertIsNone(wol.query(WOL))
            with mock.patch.object(wol.subprocess, 'run',
                                   side_effect=subprocess.TimeoutExpired('ethtool', 8)):
                self.assertIsNone(wol.query(WOL))


if __name__ == '__main__':
    unittest.main()
