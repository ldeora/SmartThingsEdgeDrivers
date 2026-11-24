"""Fixture-only authenticated-input rendering tests."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import generate_trusted_payload as packaging
import historical_expectations as expectations
import install_core as core
import payload_staging as staging


class HistoricalExpectationTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.source = Path(tmp.name)
        for name in staging.PAYLOAD_FILES:
            target = self.source / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / name, target)
        manifest = packaging.build_manifest(ROOT)
        self.version = manifest['agent_version']
        self.manifest = json.dumps(dict(schema_version=1, **manifest)).encode()
        self.digest = hashlib.sha256(self.manifest).hexdigest()

    def derive(self, **overrides):
        kwargs = dict(expected_manifest_sha256=self.digest,
                      expected_agent_version=self.version,
                      renderer='v2_fixed_plan_1',
                      python_bin='/usr/bin/python3.14',
                      power_enabled=False, wol_interface=None, avahi_present=False)
        kwargs.update(overrides)
        return expectations.derive_expectations(self.source, self.manifest, **kwargs)

    def test_rendered_variants_cover_exact_managed_set(self):
        for power in (False, True):
            for nic in (None, 'eth0'):
                for avahi in (False, True):
                    with self.subTest(power=power, nic=nic, avahi=avahi):
                        result = self.derive(power_enabled=power, wol_interface=nic,
                                             avahi_present=avahi)
                        actual = core.generate_plan(
                            ROOT, '/usr/bin/python3.14', enable_power=power,
                            disable_power=not power, wol_interface=nic,
                            is_existing_power=False, avahi_dir=avahi)
                        expected = {c.path: hashlib.sha256(c.content).hexdigest()
                                    for c in actual if c.content is not None}
                        self.assertEqual(dict(result.file_sha256), expected)
                        self.assertEqual(set(result.absent_paths),
                                         core.MANAGED_PATHS - set(expected))
                        self.assertEqual(result.release_manifest_sha256, self.digest)
                        unit = next(c for c in actual if c.path == core.SYSTEMD_PATHS[0])
                        self.assertIn(b'/usr/bin/python3.14', unit.content)

    def test_requires_independent_digest_version_and_renderer(self):
        for options in (
                {'expected_manifest_sha256': '0' * 64},
                {'expected_agent_version': '0.0.0'},
                {'renderer': 'unknown'},
                {'python_bin': '/tmp/python'},
                {'power_enabled': 'preserve'}, {'avahi_present': 1},
                {'wol_interface': '../bad'}):
            with self.subTest(options=options):
                with self.assertRaises(expectations.HistoricalExpectationError):
                    self.derive(**options)

    def test_source_changes_and_symlinks_refused(self):
        file = self.source / 'agent/linux_host_agent.py'
        file.write_bytes(file.read_bytes() + b'\n# changed')
        with self.assertRaises(expectations.HistoricalExpectationError):
            self.derive()
        file.unlink()
        file.symlink_to(ROOT / 'agent/linux_host_agent.py')
        with self.assertRaises(expectations.HistoricalExpectationError):
            self.derive()

    def test_duplicate_manifest_keys_rejected_even_with_expected_digest(self):
        self.manifest = self.manifest.replace(b'"schema_version": 1',
                                              b'"schema_version": 1, "schema_version": 1')
        self.digest = hashlib.sha256(self.manifest).hexdigest()
        with self.assertRaises(expectations.HistoricalExpectationError):
            self.derive()


# Frozen historical input and output contract, independent of the current
# release templates and of generate_plan(). The fixture scripts are data,
# not executable code. Do not regenerate these hashes from the planner.
_FIXED_PAYLOAD = {
    'agent/linux_host_agent.py':
        b'PROTOCOL = "computer-host-agent"\nVERSION = "0.0.1-fixture"\n',
    'agent/power_helper.py': b'# fixed fixture power helper\n',
    'agent/systemd/linux-host-agent.service':
        b'[Service]\nExecStart=/usr/bin/python3 /opt/linux-host-agent/linux_host_agent.py\n'
        b'ExecStartPost=/usr/bin/python3 -V\n',
    'agent/systemd/linux-host-agent-power.service':
        b'[Service]\nExecStart=/usr/bin/python3 /opt/linux-host-agent/power_helper.py\n',
    'agent/systemd/linux-host-agent-power.socket':
        b'[Socket]\nListenStream=/run/linux-host-agent-power.sock\n',
    'agent/systemd/enable-power.conf':
        b'[Service]\nExecStart=\n'
        b'ExecStart=/usr/bin/python3 /opt/linux-host-agent/linux_host_agent.py --enable-power\n',
    'agent/systemd/avahi-linux-host-agent.service':
        b'<service-group>\n<service><type>_computerhost._tcp</type><port>8765</port></service>\n'
        b'</service-group>\n',
    'scripts/install_core.py': b'# fixed fixture installer data\n',
    'scripts/runtime_verify.py': b'# fixed fixture runtime verifier data\n',
    'scripts/transaction_journal.py': b'# fixed fixture journal data\n',
}

_FIXED_COMMON_HASHES = {
    '/opt/linux-host-agent/linux_host_agent.py':
        '07ebd7f27edc06ccb11f77fa4406ff1e7d6e05bab11805a9ad361cd373a56591',
    '/opt/linux-host-agent/power_helper.py':
        '942e2233a512d0f7cfc91153fbe1b3f823e72be03269491a981e8a1630330900',
    '/etc/systemd/system/linux-host-agent-power.socket':
        'f301e26a64f01ddadfdd6d86712469731a3c032bd60b7668b254deba31c63b90',
}
_FIXED_SERVICE_HASHES = {
    '/usr/bin/python3': {
        '/etc/systemd/system/linux-host-agent.service':
            '7c7a46d6372cb1320c66a143519503a5ef7409a87a83608bb73576711128d5e6',
        '/etc/systemd/system/linux-host-agent-power.service':
            '78e6dad3b94777a3e014d08fa2b41b9884bd63f47dc189ac5406feb5d6a92252',
    },
    '/usr/bin/python3.14': {
        '/etc/systemd/system/linux-host-agent.service':
            'e92c71e505945e6ea2055ec9f523502a5b2e86b67f359e94078be9e5d1212bbb',
        '/etc/systemd/system/linux-host-agent-power.service':
            'd65ffc09882c57eb120f7f92c7c25191a54309a2e2f5332b0a5bbd1ab7be405b',
    },
}
_FIXED_POWER = '/etc/systemd/system/linux-host-agent.service.d/enable-power.conf'
_FIXED_POWER_HASHES = {
    '/usr/bin/python3':
        '903a546d6452f02269b17f6df317afc3b8ac3c9bca6bee33ba12ffff82479de4',
    '/usr/bin/python3.14':
        '8e2708084a04851a806fe0f32b1f7c75111c0e1392fa3db27bc01077f743ae99',
}
_FIXED_WOL = '/etc/systemd/system/linux-host-agent.service.d/90-wol-interface.conf'
_FIXED_WOL_HASH = 'a8c2db712e4b5a779e83fbe750f346e739602ddc1d6b349f6d286711ab9fe63d'
_FIXED_AVAHI = '/etc/avahi/services/linux-host-agent.service'
_FIXED_AVAHI_HASH = 'd3fc443dd1038bb4261b3b1c44e2b34dca63fdf2dfb77824423c601d7050aa5a'


class HistoricalRendererContractTests(unittest.TestCase):
    def test_v2_fixed_plan_1_frozen_output_contract(self):
        # The identifier is intentionally literal: changing the renderer
        # requires reviewing this old contract, not blindly refreshing it.
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp)
            for name, content in _FIXED_PAYLOAD.items():
                target = source / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(content)
            manifest = json.dumps({
                'schema_version': 1,
                'agent_version': '0.0.1-fixture',
                'files': {name: hashlib.sha256(content).hexdigest()
                          for name, content in _FIXED_PAYLOAD.items()},
            }, sort_keys=True).encode('ascii')
            digest = hashlib.sha256(manifest).hexdigest()
            for python_bin, services in _FIXED_SERVICE_HASHES.items():
                for power in (False, True):
                    for nic in (None, 'eth0'):
                        for avahi in (False, True):
                            with self.subTest(python=python_bin, power=power,
                                              nic=nic, avahi=avahi):
                                expected = dict(_FIXED_COMMON_HASHES, **services)
                                absent = []
                                for present, path, value in (
                                    (power, _FIXED_POWER, _FIXED_POWER_HASHES[python_bin]),
                                    (nic is not None, _FIXED_WOL, _FIXED_WOL_HASH),
                                    (avahi, _FIXED_AVAHI, _FIXED_AVAHI_HASH),
                                ):
                                    if present:
                                        expected[path] = value
                                    else:
                                        absent.append(path)
                                result = expectations.derive_expectations(
                                    source, manifest,
                                    expected_manifest_sha256=digest,
                                    expected_agent_version='0.0.1-fixture',
                                    renderer='v2_fixed_plan_1', python_bin=python_bin,
                                    power_enabled=power, wol_interface=nic,
                                    avahi_present=avahi)
                                self.assertEqual(result.renderer, 'v2_fixed_plan_1')
                                self.assertEqual(result.agent_version, '0.0.1-fixture')
                                self.assertEqual(result.release_manifest_sha256, digest)
                                self.assertEqual(result.file_sha256, tuple(sorted(expected.items())),
                                                 'renderer output changed; review compatibility')
                                self.assertEqual(result.absent_paths, tuple(sorted(absent)),
                                                 'renderer coverage changed; review compatibility')


if __name__ == '__main__':
    unittest.main()
