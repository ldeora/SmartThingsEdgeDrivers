"""Static contract checks only: these do NOT compile or execute C# on Windows."""
import json
from pathlib import Path
import unittest
import yaml

ROOT=Path(__file__).resolve().parents[1]
WINDOWS=ROOT / 'windows-agent'

class WindowsPhase2SourceTests(unittest.TestCase):
    def test_windows_agent_declares_same_wire_contract(self):
        contract=json.loads((ROOT/'shared/contract-v2.json').read_text())
        c=(WINDOWS/'ComputerHost.WindowsAgent/AgentContract.cs').read_text()
        self.assertIn('"'+contract['name']+'"',c)
        self.assertIn('const int ApiVersion = 2',c)
        self.assertIn('"_computerhost._tcp.local"',c)
        self.assertIn('SupportedPowerActions = [',c)
        p=(WINDOWS/'ComputerHost.WindowsAgent/Program.cs').read_text()
        for route in ('/v2/info','/v2/health','/v2/metrics','/v2/challenge','/v2/power/{action}'):
            self.assertIn('"'+route+'"',p)
        self.assertIn('Results.StatusCode(403)',p)

    def test_windows_profile_supports_opt_in_power(self):
        windows=yaml.safe_load((ROOT/'edge-driver/profiles/computer-host-windows.yaml').read_text())
        linux=yaml.safe_load((ROOT/'edge-driver/profiles/computer-host-linux.yaml').read_text())
        self.assertEqual([x['id'] for x in windows['components']],['main','wake','reboot','suspend'])
        self.assertEqual([x['id'] for x in linux['components']],['main','wake','reboot','suspend'])
        for profile in (linux, windows):
            self.assertEqual({c['id']: c['label'] for c in profile['components']},
                             {'main':'Computer', 'wake':'Wake', 'reboot':'Restart', 'suspend':'Sleep'})
        excluded={'controlKey','allowPowerCommands','wolPort','wolMacOverride','wolBroadcastOverride'}
        self.assertTrue(excluded.issubset(x['name'] for x in windows['preferences']))

    def test_windows_no_linux_file_access(self):
        sources='\n'.join(f.read_text() for f in (WINDOWS/'ComputerHost.WindowsAgent').glob('*.cs'))
        for linux_marker in ('/proc/stat','/proc/meminfo','/sys/class/hwmon','systemctl','ethtool'):
            self.assertNotIn(linux_marker,sources)
        for windows_api in ('GetSystemTimes','GlobalMemoryStatusEx','GetTickCount64','DnsServiceRegister'):
            self.assertIn(windows_api,sources)

    def test_ci_windows_contract_and_publish_source(self):
        workflow=(ROOT.parent / '.github/workflows/computer-host-windows.yml').read_text() if (ROOT.parent / '.github/workflows/computer-host-windows.yml').exists() else ''
        if not workflow:
            self.skipTest('Active workflow resides at monorepo root, omitted in standalone source archive')
        self.assertIn('runs-on: windows-2025',workflow)
        self.assertIn('dotnet run --project windows-agent/ComputerHost.WindowsAgent.Tests/',workflow)
        self.assertIn('Smoke-WindowsAgent.ps1',workflow)
        self.assertTrue((WINDOWS/'scripts/Install-WindowsAgent.ps1').is_file())
        self.assertTrue((WINDOWS/'scripts/Uninstall-WindowsAgent.ps1').is_file())

if __name__=='__main__': unittest.main()
