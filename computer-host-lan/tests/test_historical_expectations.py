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


if __name__ == '__main__':
    unittest.main()
