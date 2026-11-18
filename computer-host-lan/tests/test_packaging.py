import json
from pathlib import Path
import unittest
import yaml

ROOT=Path(__file__).resolve().parents[1]

class StaticChecks(unittest.TestCase):
    def test_profile_and_config(self):
        config=yaml.safe_load((ROOT/'edge-driver/config.yaml').read_text())
        self.assertEqual(config['packageKey'],'computer-host-lan')
        self.assertIn('lan',config['permissions'])
        profile=yaml.safe_load((ROOT/'edge-driver/profiles/computer-host.yaml').read_text())
        self.assertEqual(profile['name'],'computer-host')
        self.assertEqual(profile['components'][0]['capabilities'][0]['id'],'switch')
        self.assertEqual({x['id'] for x in profile['components'][1:]}, {'wake','suspend','reboot'})
        self.assertNotIn('presenceSensor',str(profile))
        advanced=yaml.safe_load((ROOT/'edge-driver/profiles/computer-host-linux.yaml').read_text())
        self.assertEqual(advanced['name'],'computer-host-linux')
        advanced_ids={cap['id'] for cap in advanced['components'][0]['capabilities']}
        self.assertTrue({'oceancircle09600.computerHostStatus','oceancircle09600.computerCpuUsage',
                         'oceancircle09600.computerMemoryUsage','oceancircle09600.computerDiskUsage',
                         'oceancircle09600.computerUptime','oceancircle09600.linuxLoad'}.issubset(advanced_ids))
        constants=(ROOT/'edge-driver/src/computerhost/constants.lua').read_text()
        self.assertIn('M.PROFILE_NAME = "computer-host-linux"',constants)
        prefs={x['name']:x for x in profile['preferences']}
        self.assertIn('assumeOffWhenUnreachable', prefs)
        self.assertTrue(prefs['assumeOffWhenUnreachable']['definition']['default'])
        self.assertEqual(prefs['failureThreshold']['definition']['default'],3)

    def test_preference_titles_within_smartthings_limits(self):
        for path in [
            ROOT/'edge-driver/profiles/computer-host.yaml',
            ROOT/'edge-driver/profiles/computer-host-linux.yaml',
        ]:
            with self.subTest(profile=path.name):
                profile=yaml.safe_load(path.read_text())
                for preference in profile.get('preferences', []):
                    title=preference['title']
                    with self.subTest(preference=preference['name']):
                        self.assertGreaterEqual(len(title), 3)
                        self.assertLessEqual(len(title), 36)

    def test_custom_capability_files(self):
        files=list((ROOT/'edge-driver/custom-capabilities').glob('*.json'))
        self.assertEqual(len(files),24)
        for file in files:
            with self.subTest(file=file.name):
                obj=json.loads(file.read_text())
                self.assertTrue(obj)
        cpu=json.loads((ROOT/'edge-driver/custom-capabilities/computerCpuUsage.json').read_text())
        self.assertEqual(cpu['name'],'Computer Cpu Usage')
        load=json.loads((ROOT/'edge-driver/custom-capabilities/linuxLoad.json').read_text())
        self.assertEqual(load['name'],'Linux Load')
        self.assertEqual(set(load['attributes']),{'loadOne','loadFive','loadFifteen'})
        uptime=json.loads((ROOT/'edge-driver/custom-capabilities/computerUptime.json').read_text())
        self.assertEqual(uptime['name'],'Computer Uptime')
        self.assertEqual(set(uptime['attributes']),{'uptimeMinutes','uptimeText'})
        memory=json.loads((ROOT/'edge-driver/custom-capabilities/computerMemoryUsage.json').read_text())
        self.assertEqual(set(memory['attributes']),{'memoryUsage','memoryTotalGiB','memoryUsedGiB','memoryAvailableGiB'})
        disk=json.loads((ROOT/'edge-driver/custom-capabilities/computerDiskUsage.json').read_text())
        self.assertEqual(disk['name'],'Computer Disk Usage')
        for definition_path in (ROOT/'edge-driver/custom-capabilities').glob('*.json'):
            if definition_path.name.endswith(('.presentation.json','.de.json','.en.json')):
                continue
            name=definition_path.stem
            definition=json.loads(definition_path.read_text())
            presentation=json.loads((definition_path.parent/f'{name}.presentation.json').read_text())
            self.assertEqual(presentation['id'],f'oceancircle09600.{name}')
            available=set(definition['attributes'])
            self.assertTrue({'dashboard','detailView','automation'}.issubset(presentation))
            import re
            serialized=json.dumps(presentation)
            referenced=set(re.findall(r'\{\{([A-Za-z][A-Za-z0-9]*)\.value\}\}',serialized))
            self.assertTrue(referenced.issubset(available), (name,referenced-available))
            self.assertTrue(all(item['displayType'] in {'numberField','list'}
                                for item in presentation['automation']['conditions']))
            for lang in ('en','de'):
                translation=json.loads((definition_path.parent/f'{name}.{lang}.json').read_text())
                self.assertEqual(translation['tag'],lang)
                self.assertEqual(set(translation['attributes']),available)
                self.assertTrue(translation['label'])

    def test_service_uses_non_root_agent(self):
        txt=(ROOT/'agent/systemd/linux-host-agent.service').read_text()
        self.assertIn('User=linuxhost',txt)
        self.assertIn('After=network.target',txt)
        self.assertNotIn('network-online.target',txt)
        self.assertNotIn('User=root',txt)
        self.assertNotIn('--enable-power-control',txt)
        self.assertIn('--enable-power-control',(ROOT/'agent/systemd/enable-power.conf').read_text())
        installer=(ROOT/'scripts/install-agent.sh').read_text()
        self.assertIn('--configure-wol', installer)
        self.assertIn('scripts/configure-wol.sh',installer)
        self.assertIn('linux-host-agent-power.socket', (ROOT/'scripts/install_core.py').read_text())
        self.assertIn('--wol-interface', installer)
        self.assertIn('LINUX_HOST_WOL_INTERFACE', (ROOT/'scripts/install_core.py').read_text())
        helper=(ROOT/'agent/systemd/linux-host-agent-power.socket').read_text()
        self.assertIn('SocketMode=0660',helper)

if __name__=='__main__': unittest.main()
