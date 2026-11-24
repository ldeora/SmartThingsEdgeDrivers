"""Read-only policy fixtures; no actual systemd/nmcli/ethtool calls."""
import json
import os
import pwd
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import wol_plan as planner

IFACE = 'enp1s0f0'
MAC = '02:11:22:33:44:55'
OTHER = '02:ab:cd:ef:11:22'
PROFILE = 'aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee'
LOCAL = '/etc/systemd/network/10-wol.link'
VENDOR = '/usr/lib/systemd/network/99-default.link'
WOL = ('ethtool', IFACE)
IOCTL = ('ethtool', '--disable-netlink', IFACE)
PERM = ('ethtool', '-P', IFACE)
NM = ('systemctl', 'show', '--all', '--no-pager',
      '--property=LoadState,ActiveState', '--', 'NetworkManager.service')
NM_UUID = ('nmcli', '--wait', '5', '--get-values',
           'GENERAL.CON-UUID', 'device', 'show', IFACE)
NM_POLICY = ('nmcli', '--wait', '5', '--get-values',
             '802-3-ethernet.wake-on-lan', 'connection', 'show', 'uuid', PROFILE)
UDEV = ('udevadm', 'info', '--query=property', '--path=/sys/class/net/' + IFACE)


def exact_rule(mac=MAC, wol='magic', key='PermanentMACAddress'):
    return '[Match]\n' + key + '=' + mac + '\n[Link]\nWakeOnLan=' + wol + '\n'


class WolPlannerTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.net = self.root / 'sys/class/net'
        nic = self.net / IFACE
        (nic / 'device').mkdir(parents=True)
        (nic / 'ifindex').write_text('4\n')
        (nic / 'type').write_text('1\n')
        (nic / 'address').write_text(MAC + '\n')
        self.put(LOCAL, exact_rule())
        self.put(VENDOR, '[Match]\nOriginalName=*\n[Link]\nNamePolicy=keep\n')
        self.calls = []
        self.replies = {
            WOL: 'Supports Wake-on: pumbg\nWake-on: g\n',
            PERM: 'Permanent address: ' + MAC + '\n',
            NM: 'LoadState=not-found\nActiveState=inactive\n',
            UDEV: 'ID_NET_LINK_FILE=' + LOCAL + '\n',
        }

    def put(self, path, contents):
        file = self.root / path.lstrip('/')
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(contents)
        return file

    def run_query(self, args):
        self.calls.append(args)
        reply = self.replies.get(args)
        return reply() if callable(reply) else reply

    def plan(self):
        result = planner.plan(IFACE, root=self.root, net=self.net,
                              owner_uid=os.getuid(), run=self.run_query)
        self.assertFalse(result['automatic_changes_allowed'])
        self.assertFalse(result['changes_applied'])
        self.assertFalse(result['persistence_verified'])
        self.assertFalse(result['secrets_included'])
        for private in (MAC, OTHER, PROFILE, IFACE, LOCAL, VENDOR):
            self.assertNotIn(private, json.dumps(result))
        return result

    def test_preserve_existing_local_magic_policy(self):
        before = (self.root / LOCAL.lstrip('/')).read_bytes()
        result = self.plan()
        self.assertEqual(result['recommendation'], 'preserve')
        self.assertEqual(result['link_tree'], 'base_rule_observed')
        self.assertEqual(result['link_scope'], 'permanent_mac')
        self.assertEqual(result['link_policy_evidence'], 'magic_declared')
        self.assertEqual((self.root / LOCAL.lstrip('/')).read_bytes(), before)
        self.assertEqual(self.calls, [WOL, PERM, NM, UDEV, UDEV])

    def test_current_mac_rule_is_preserved_but_not_edit_candidate(self):
        self.put(LOCAL, exact_rule(key='MACAddress'))
        self.assertEqual(self.plan()['recommendation'], 'preserve')
        self.put(LOCAL, exact_rule(wol='', key='MACAddress'))
        self.assertEqual(self.plan()['recommendation'], 'manual_review')

    def test_unprivileged_missing_wol_lines_preserves_policy_evidence(self):
        self.replies[WOL] = 'Settings for Ethernet\n'
        self.replies[IOCTL] = 'Settings for Ethernet\n'
        result = self.plan()
        self.assertEqual(result['recommendation'], 'verify_hardware')
        self.assertEqual(result['link_policy_evidence'], 'magic_declared')
        self.assertEqual(result['inspection']['runtime_magic_packet'], 'not_verified')

    def test_unsupported_hardware_never_candidate(self):
        self.replies[WOL] = 'Supports Wake-on: p\nWake-on: d\n'
        self.assertEqual(self.plan()['recommendation'], 'unavailable')

    def test_runtime_mismatch_never_rewrites_existing_policy(self):
        self.replies[WOL] = 'Supports Wake-on: pumbg\nWake-on: d\n'
        result = self.plan()
        self.assertEqual(result['recommendation'], 'review_runtime')
        self.assertEqual(result['reason'], 'link_magic_declared_runtime_differs')

    def test_only_exact_local_permanent_mac_without_wol_is_dropin_candidate(self):
        self.put(LOCAL, exact_rule(wol=''))
        self.assertEqual(self.plan()['recommendation'], 'review_link_dropin')
        self.put(LOCAL, exact_rule(wol='off'))
        self.assertEqual(self.plan()['recommendation'], 'manual_review')
        self.put(LOCAL, exact_rule(wol='phy'))
        self.assertEqual(self.plan()['recommendation'], 'manual_review')
        self.put(LOCAL, '[Match]\nOriginalName=*\n[Link]\nNamePolicy=keep\n')
        self.assertEqual(self.plan()['recommendation'], 'manual_review')

    def test_default_rule_never_shadowed(self):
        (self.root / LOCAL.lstrip('/')).unlink()
        self.replies[UDEV] = 'ID_NET_LINK_FILE=' + VENDOR + '\n'
        result = self.plan()
        self.assertEqual(result['link_scope'], 'shared_or_complex')
        self.assertEqual(result['recommendation'], 'manual_review')

    def test_earlier_generic_rule_blocks_candidate(self):
        self.put('/usr/lib/systemd/network/05-generic.link',
                 '[Match]\nDriver=*\n[Link]\nNamePolicy=keep\n')
        result = self.plan()
        self.assertEqual(result['link_tree'], 'earlier_rule_requires_review')
        self.assertEqual(result['recommendation'], 'manual_review')

    def test_earlier_permanent_mac_mismatch_excluded(self):
        self.put('/usr/lib/systemd/network/05-other.link', exact_rule(mac=OTHER))
        self.assertEqual(self.plan()['recommendation'], 'preserve')
        self.put('/usr/lib/systemd/network/05-other.link',
                 exact_rule(mac=OTHER, key='MACAddress'))
        self.assertEqual(self.plan()['link_tree'], 'earlier_rule_requires_review')

    def test_higher_priority_same_basename_invalidates_stale_selection(self):
        path = '/usr/lib/systemd/network/10-wol.link'
        self.put(path, exact_rule())
        self.replies[UDEV] = 'ID_NET_LINK_FILE=' + path + '\n'
        self.assertEqual(self.plan()['link_tree'], 'selection_changed')

    def test_masks_and_same_basename_precedence(self):
        lower = '/usr/lib/systemd/network/05-earlier.link'
        self.put(lower, '[Match]\nOriginalName=*\n[Link]\nNamePolicy=keep\n')
        mask = self.root / 'etc/systemd/network/05-earlier.link'
        mask.symlink_to('/dev/null')
        self.assertEqual(self.plan()['recommendation'], 'preserve')
        mask.unlink()
        mask.write_text('')
        self.assertEqual(self.plan()['recommendation'], 'preserve')
        mask.write_text(exact_rule())
        self.assertEqual(self.plan()['link_tree'], 'earlier_rule_requires_review')

    def empty_dropin(self):
        self.put(LOCAL, exact_rule(wol=''))
        directory = self.root / (LOCAL.lstrip('/') + '.d')
        directory.mkdir()
        return directory

    def test_protected_empty_local_dropin_is_review_candidate_only(self):
        directory = self.empty_dropin()
        result = self.plan()
        self.assertEqual(result['link_tree'], 'empty_local_dropin_observed')
        self.assertEqual(result['recommendation'], 'review_link_dropin')
        self.assertEqual(result['reason'], 'protected_empty_local_dropin')
        self.assertEqual(list(directory.iterdir()), [])

    def test_empty_dropin_does_not_extend_rule_scope_or_override_policy(self):
        self.empty_dropin()
        for rule in (exact_rule(wol='', key='MACAddress'),
                     exact_rule(wol='off'), exact_rule(wol='magic'),
                     '[Match]\nOriginalName=*\n[Link]\n'):
            with self.subTest(rule=rule):
                self.put(LOCAL, rule)
                result = self.plan()
                self.assertEqual(result['link_tree'], 'dropins_require_review')
                self.assertEqual(result['recommendation'], 'manual_review')

    def test_empty_dropin_conflicts_with_other_relevant_directories(self):
        self.empty_dropin()
        for path in ('/run/systemd/network/10-wol.link.d',
                     '/usr/lib/systemd/network/10-wol.link.d',
                     '/etc/systemd/network/05-other.link.d',
                     '/etc/systemd/network/link.d',
                     '/etc/systemd/network/10-.link.d'):
            with self.subTest(path=path):
                other = self.root / path.lstrip('/')
                other.mkdir(parents=True)
                self.assertEqual(self.plan()['link_tree'], 'dropins_require_review')
                other.rmdir()

    def test_empty_dropin_refuses_every_entry_even_hidden_or_dangling(self):
        directory = self.empty_dropin()
        for name in ('.hidden', 'unrelated.txt', '90-computer-host-wol.conf'):
            with self.subTest(name=name):
                entry = directory / name
                entry.symlink_to('/nonexistent')
                self.assertEqual(self.plan()['link_tree'], 'dropins_require_review')
                entry.unlink()
        nested = directory / 'nested'
        nested.mkdir()
        self.assertEqual(self.plan()['link_tree'], 'dropins_require_review')

    def test_empty_dropin_rejects_unsafe_directory_and_symlink(self):
        directory = self.empty_dropin()
        directory.chmod(0o777)
        self.assertNotEqual(self.plan()['recommendation'], 'review_link_dropin')
        directory.rmdir()
        other = self.root / 'private'
        other.mkdir()
        directory.symlink_to(other)
        self.assertNotEqual(self.plan()['recommendation'], 'review_link_dropin')

    def test_empty_dropin_populated_during_final_udev_query_is_refused(self):
        directory = self.empty_dropin()
        calls = 0
        def udev():
            nonlocal calls
            calls += 1
            if calls == 2:
                (directory / '.hidden').write_text('changed')
            return 'ID_NET_LINK_FILE=' + LOCAL + '\n'
        self.replies[UDEV] = udev
        self.assertEqual(self.plan()['link_tree'], 'selection_changed')

    def test_empty_dropin_replaced_during_final_udev_query_is_refused(self):
        directory = self.empty_dropin()
        calls = 0
        def udev():
            nonlocal calls
            calls += 1
            if calls == 2:
                directory.rename(directory.with_name('old-directory'))
                directory.mkdir()
            return 'ID_NET_LINK_FILE=' + LOCAL + '\n'
        self.replies[UDEV] = udev
        self.assertEqual(self.plan()['link_tree'], 'selection_changed')

    def test_empty_dropin_rule_changes_during_final_udev_query_are_refused(self):
        self.empty_dropin()
        calls = 0

        def udev():
            nonlocal calls
            calls += 1
            if calls == 2:
                self.put(LOCAL, exact_rule(wol='off'))
            return 'ID_NET_LINK_FILE=' + LOCAL + '\n'

        self.replies[UDEV] = udev
        self.assertEqual(self.plan()['link_tree'], 'selection_changed')

    def test_empty_dropin_never_overrides_reported_or_earlier_conflict(self):
        self.empty_dropin()
        self.replies[UDEV] += 'ID_NET_LINK_FILE_DROPINS=/private/override.conf\n'
        self.assertEqual(self.plan()['link_tree'], 'dropins_require_review')
        self.replies[UDEV] = 'ID_NET_LINK_FILE=' + LOCAL + '\n'
        self.put('/usr/lib/systemd/network/05-generic.link',
                 '[Match]\nDriver=*\n[Link]\n')
        self.assertEqual(self.plan()['link_tree'], 'earlier_rule_requires_review')

    def test_on_disk_dropin_detected_even_if_udev_did_not_report(self):
        self.put('/run/systemd/network/10-wol.link.d/20-other.conf',
                 '[Link]\nWakeOnLan=off\n')
        result = self.plan()
        self.assertEqual(result['link_tree'], 'dropins_require_review')
        self.assertEqual(result['link_policy_evidence'], 'not_verified')
        self.assertEqual(result['recommendation'], 'manual_review')

    def test_earlier_dropin_could_change_match(self):
        self.put('/usr/lib/systemd/network/05-other.link', exact_rule(mac=OTHER))
        self.put('/etc/systemd/network/05-other.link.d/override.conf',
                 '[Match]\nPermanentMACAddress=\n')
        self.assertEqual(self.plan()['link_tree'], 'dropins_require_review')

    def test_observed_dropin_blocks_even_if_no_file_seen(self):
        self.replies[UDEV] += 'ID_NET_LINK_FILE_DROPINS=/private/override.conf\n'
        result = self.plan()
        self.assertEqual(result['link_tree'], 'dropins_require_review')
        self.assertNotIn('/private/override.conf', json.dumps(result))

    def test_unexpected_symlink_and_writable_rules_are_unknown(self):
        earlier = self.put('/etc/systemd/network/05-earlier.link', exact_rule(mac=OTHER))
        earlier.chmod(0o666)
        self.assertEqual(self.plan()['link_tree'], 'not_verified')
        earlier.unlink()
        earlier.symlink_to('/private/sensitive.link')
        self.assertEqual(self.plan()['link_tree'], 'not_verified')

    def test_unsafe_directory_is_unknown(self):
        (self.root / 'etc/systemd/network').chmod(0o777)
        self.assertEqual(self.plan()['link_tree'], 'not_verified')

    def test_merged_usr_alias_and_distinct_vendor_dirs(self):
        (self.root / 'lib').symlink_to('usr/lib')
        self.assertEqual(self.plan()['recommendation'], 'preserve')
        (self.root / 'lib').unlink()
        self.put('/lib/systemd/network/50-extra.link', exact_rule(mac=OTHER))
        self.assertEqual(self.plan()['link_tree'], 'not_verified')

    def test_runtime_only_policy_is_not_persistence_evidence(self):
        runtime = '/run/systemd/network/05-wol.link'
        self.put(runtime, exact_rule())
        self.replies[UDEV] = 'ID_NET_LINK_FILE=' + runtime + '\n'
        result = self.plan()
        self.assertEqual(result['link_tree'], 'base_rule_observed')
        self.assertEqual(result['recommendation'], 'manual_review')

    def test_secureon_requires_review_and_never_leaks_password(self):
        self.put(LOCAL, exact_rule() + 'WakeOnLanPassword=DO-NOT-EMIT\n')
        result = self.plan()
        self.assertEqual(result['reason'], 'secureon_requires_review')
        self.assertNotIn('DO-NOT-EMIT', json.dumps(result))
        self.put(LOCAL, exact_rule())
        self.replies[WOL] = 'Supports Wake-on: pumbgs\nWake-on: gs\n'
        self.assertEqual(self.plan()['reason'], 'secureon_requires_review')

    def test_selection_changed_between_queries(self):
        responses = iter(('ID_NET_LINK_FILE=' + LOCAL + '\n',
                          'ID_NET_LINK_FILE=' + VENDOR + '\n'))
        self.replies[UDEV] = lambda: next(responses)
        self.assertEqual(self.plan()['link_tree'], 'selection_changed')

    def test_interface_changed_after_tree_inspection(self):
        count = 0
        def udev():
            nonlocal count
            count += 1
            if count == 2:
                (self.net / IFACE / 'ifindex').write_text('5\n')
            return 'ID_NET_LINK_FILE=' + LOCAL + '\n'
        self.replies[UDEV] = udev
        result = self.plan()
        self.assertEqual(result['inspection']['interface_state'], 'interface_changed')
        self.assertEqual(result['recommendation'], 'unavailable')

    def test_nm_explicit_flags_preserve_or_review_only(self):
        self.replies.update({
            NM: 'LoadState=loaded\nActiveState=active\n',
            NM_UUID: PROFILE + '\n',
        })
        for flags, expected in (
                ('magic', 'preserve'), ('phy, magic', 'preserve'),
                ('0', 'review_nm_add_magic'), ('phy, multicast', 'review_nm_add_magic'),
                ('default', 'manual_review'), ('ignore', 'manual_review'),
                ('--', 'manual_review')):
            with self.subTest(flags=flags):
                self.replies[NM_POLICY] = flags
                result = self.plan()
                self.assertEqual(result['recommendation'], expected)
                if flags == '0':
                    self.assertEqual(result['reason'], 'explicit_nm_wol_disabled')
                elif flags == 'phy, multicast':
                    self.assertEqual(result['reason'], 'explicit_nm_flags_without_magic')
                self.assertEqual(result['link_tree'], 'not_verified')
        self.assertNotIn(UDEV, self.calls)

    def test_nm_runtime_mismatch_not_a_profile_change(self):
        self.replies.update({
            NM: 'LoadState=loaded\nActiveState=active\n',
            NM_UUID: PROFILE + '\n', NM_POLICY: 'magic',
            WOL: 'Supports Wake-on: pumbg\nWake-on: d\n',
        })
        self.assertEqual(self.plan()['recommendation'], 'review_runtime')

    def test_ambiguous_nm_never_falls_back_to_link(self):
        self.replies[NM] = 'LoadState=loaded\nActiveState=active\n'
        self.replies[NM_UUID] = '--\n'
        self.assertEqual(self.plan()['recommendation'], 'manual_review')
        self.assertNotIn(UDEV, self.calls)

    def test_permanent_mac_mismatch_blocks_changes(self):
        self.replies[PERM] = 'Permanent address: ' + OTHER + '\n'
        self.assertEqual(self.plan()['reason'], 'interface_identity_not_verified')

    def test_inventory_change_after_shared_read_invalidates_plan(self):
        original = planner.inventory
        calls = 0

        def changed(root, owner_uid):
            nonlocal calls
            calls += 1
            if calls == 2:
                self.put('/etc/systemd/network/05-new.link', exact_rule())
            return original(root, owner_uid)

        with mock.patch.object(planner, 'inventory', side_effect=changed):
            result = self.plan()
        self.assertEqual(calls, 2)
        self.assertEqual(result['link_tree'], 'selection_changed')
        self.assertEqual(result['recommendation'], 'manual_review')

    def test_inventory_failure_does_not_retry_as_verified(self):
        with mock.patch.object(planner, 'inventory',
                               side_effect=planner.UncertainPolicy()) as scan:
            result = self.plan()
        scan.assert_called_once()
        self.assertEqual(result['link_tree'], 'not_verified')
        self.assertEqual(result['recommendation'], 'manual_review')

    def test_standalone_isolated_mode_and_unsafe_sibling(self):
        # Do not use /tmp or environment HOME: GitHub container jobs
        # run as root with HOME=/github/home, a mounted runner directory
        # that need not satisfy the root source ownership contract.
        # Use the actual account's home from passwd instead.
        account_home = Path(pwd.getpwuid(os.geteuid()).pw_dir)
        with tempfile.TemporaryDirectory(dir=account_home) as directory:
            dest = Path(directory)
            for name in ('wol_plan.py', 'wol_inspect.py'):
                shutil.copyfile(ROOT / 'scripts' / name, dest / name)
                (dest / name).chmod(0o600)
            command = [sys.executable, '-I', '-S', '-B',
                       str(dest / 'wol_plan.py'), '--interface', '../invalid']
            done = subprocess.run(command, cwd='/', capture_output=True,
                                  text=True, timeout=15)
            self.assertEqual(done.returncode, 0, done.stderr)
            self.assertEqual(json.loads(done.stdout)['recommendation'], 'unavailable')
            # A private file is insufficient if its directory is writable.
            dest.chmod(0o777)
            try:
                done = subprocess.run(command, cwd='/', capture_output=True,
                                      text=True, timeout=15)
                self.assertNotEqual(done.returncode, 0)
                self.assertIn('unsafe inspector import directory', done.stderr)
                self.assertEqual(done.stdout, '')
            finally:
                dest.chmod(0o700)
            sibling = dest / 'wol_inspect.py'
            sibling.chmod(0o666)
            done = subprocess.run(command, cwd='/', capture_output=True,
                                  text=True, timeout=15)
            self.assertNotEqual(done.returncode, 0)
            self.assertIn('unsafe inspector source', done.stderr)
            self.assertEqual(done.stdout, '')
            sibling.unlink()
            sibling.symlink_to(ROOT / 'scripts' / 'wol_inspect.py')
            done = subprocess.run(command, cwd='/', capture_output=True,
                                  text=True, timeout=15)
            self.assertNotEqual(done.returncode, 0)
            self.assertEqual(done.stdout, '')

    def test_invalid_interface_does_not_execute_commands(self):
        result = planner.plan('../private', root=self.root, net=self.net,
                              owner_uid=os.getuid(), run=self.run_query)
        self.assertEqual(result['recommendation'], 'unavailable')
        self.assertEqual(self.calls, [])


if __name__ == '__main__':
    unittest.main()
