"""v2 Linux source conformance + Windows-compatible Edge discovery contract.

These tests do not constitute Windows hardware validation or SmartThings-hub
validation. They check the cross-platform contract against real Lua execution.
"""
import ctypes
from ctypes.util import find_library
import json
from pathlib import Path
import sys
import unittest
from http.server import ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import urlopen
import threading

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'agent'))
import linux_host_agent as agent


class AgentV2ContractTests(unittest.TestCase):
    def setUp(self):
        self.state = agent.AgentState('bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb',
                                      '0a' * 32, False, '', None, None)
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), agent.make_handler(self.state))
        self.worker = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.worker.start()
        self.base = f'http://127.0.0.1:{self.server.server_port}'

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.worker.join(timeout=2)

    def test_every_successful_endpoint_uses_generic_platform_contract(self):
        expected_paths = ('info', 'health', 'metrics')
        for endpoint in expected_paths:
            with self.subTest(endpoint=endpoint):
                with urlopen(self.base + '/v2/' + endpoint, timeout=3) as response:
                    self.assertEqual(response.status, 200)
                    obj = json.load(response)
                for key, value in {
                    'protocol': 'computer-host-agent', 'api_version': 2,
                    'platform': 'linux', 'id': self.state.identifier,
                }.items():
                    self.assertEqual(obj[key], value)
        info = json.load(urlopen(self.base + '/v2/info', timeout=3))
        self.assertEqual(info['power_actions'], [])
        self.assertNotIn('power-control', info['features'])

    def test_old_protocol_routes_are_not_implicitly_supported(self):
        for path in ('/v1/info', '/v1/health', '/v1/metrics', '/v1/challenge'):
            with self.subTest(path=path), self.assertRaises(HTTPError) as exc:
                urlopen(self.base + path, timeout=3)
            self.assertEqual(exc.exception.code, 404)

    def test_advertisement_matches_linux_agent_v2(self):
        advertisement = (ROOT / 'agent/systemd/avahi-linux-host-agent.service').read_text()
        self.assertIn('<type>_computerhost._tcp</type>', advertisement)
        self.assertIn('api=2', advertisement)
        self.assertIn('platform=linux', advertisement)
        self.assertIn('computer-host-agent', advertisement)

    def test_pending_platform_applied_before_initial_profile_check(self):
        driver = (ROOT / 'edge-driver/src/init.lua').read_text()
        start = driver.index('local function init(driver,device)')
        end = driver.index('local function removed(', start)
        body = driver[start:end]
        self.assertLess(body.index('D.apply_pending(device)'),
                        body.index('ensure_profile(device)'))

    def test_shared_contract_signature_matches_python_and_wire_path(self):
        import hmac
        import hashlib
        contract = json.loads((ROOT / 'shared/contract-v2.json').read_text())
        self.assertEqual(contract['name'], agent.PROTOCOL)
        self.assertEqual(contract['api_version'], agent.API_VERSION)
        self.assertEqual(contract['service_type'], '_computerhost._tcp')
        self.assertEqual(contract['routes']['reboot'], 'POST /v2/power/reboot')
        spec = contract['signature']
        vector = spec['test_vector']
        self.assertEqual(spec['signature_header'], 'X-ComputerHost-Signature')
        self.assertEqual(agent.signature(vector['key_hex'], vector['path'], vector['nonce']),
                         vector['expected_signature_hex'])
        self.assertEqual(vector['expected_signature_hex'], hmac.new(
            bytes.fromhex(vector['key_hex']),
            ('POST\n'+vector['path']+'\n'+vector['nonce']+'\n').encode('ascii'),
            hashlib.sha256).hexdigest())

    def test_linux_metrics_are_not_dropped_in_generic_profile(self):
        import yaml
        profile = yaml.safe_load((ROOT / 'edge-driver/profiles/computer-host-linux.yaml').read_text())
        windows = yaml.safe_load((ROOT / 'edge-driver/profiles/computer-host-windows.yaml').read_text())
        def capabilities(config):
            return {c['id'] for c in config['components'][0]['capabilities']}
        linux_caps, windows_caps = capabilities(profile), capabilities(windows)
        self.assertEqual(linux_caps - windows_caps, {'oceancircle09600.linuxLoad', 'temperatureMeasurement'})
        for cap in ('switch', 'refresh',
                    'oceancircle09600.computerHostStatus',
                    'oceancircle09600.computerCpuUsage',
                    'oceancircle09600.computerMemoryUsage',
                    'oceancircle09600.computerDiskUsage',
                    'oceancircle09600.computerUptime'):
            self.assertIn(cap, linux_caps)
            self.assertIn(cap, windows_caps)
        self.assertEqual({c['id'] for c in profile['components']},
                         {'main', 'wake', 'reboot', 'suspend'})
        self.assertEqual({c['id'] for c in windows['components']},
                         {'main', 'wake', 'reboot', 'suspend'})
        self.assertIn('temperatureMeasurement', linux_caps)
        self.assertIn('allowPowerCommands', {p['name'] for p in windows['preferences']})


class DiscoveryV2ContractTests(unittest.TestCase):
    def test_linux_and_windows_agents_create_distinct_appropriate_profiles(self):
        library = find_library('lua5.4') or find_library('lua5.3')
        if not library:
            self.skipTest('Lua runtime library unavailable')
        lib = ctypes.CDLL(library)
        lib.luaL_newstate.restype = ctypes.c_void_p
        lib.luaL_openlibs.argtypes = [ctypes.c_void_p]
        lib.luaL_loadstring.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
        lib.luaL_loadstring.restype = ctypes.c_int
        lib.lua_pcallk.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                   ctypes.c_ssize_t, ctypes.c_void_p]
        lib.lua_pcallk.restype = ctypes.c_int
        lib.lua_tolstring.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p]
        lib.lua_tolstring.restype = ctypes.c_char_p
        lib.lua_close.argtypes = [ctypes.c_void_p]
        path = (ROOT / 'edge-driver/src').as_posix()
        script = r'''
            package.path=%s .. '/?.lua;' .. %s .. '/?/init.lua;' .. package.path
            package.loaded.log={warn=function() end, info=function() end}
            package.loaded['st.mdns']={discover=function() return {found={}} end}
            local linux_id='aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'
            local windows_id='bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb'
            package.loaded['computerhost.api']={fetch_info=function(host)
              if host=='192.0.2.10' then
                return {id=linux_id,platform='linux',hostname='linuxbox',power_actions={'shutdown'}}
              elseif host=='192.0.2.11' then
                return {id=windows_id,platform='windows',hostname='winbox',power_actions={'suspend'}}
              end
              return nil,'unexpected host'
            end}
            local D=require 'computerhost.discovery'
            local C=require 'computerhost.constants'
            assert(C.PROTOCOL_VERSION==2)
            assert(C.MDNS_SERVICE_TYPE=='_computerhost._tcp')
            local created={}
            local driver={}
            function driver:get_devices() return {} end
            function driver:try_create_device(metadata) created[#created+1]=metadata end
            assert(D.process_candidate(driver,{host='192.0.2.10',port=8765})==nil)
            assert(D.process_candidate(driver,{host='192.0.2.11',port=8765})==nil)
            assert(#created==2)
            assert(created[1].profile=='computer-host-linux')
            assert(created[2].profile=='computer-host-windows')
            assert(created[1].device_network_id=='computer-host:'..linux_id)
            assert(created[2].device_network_id=='computer-host:'..windows_id)
            assert(created[1].model=='Linux Computer')
            assert(created[2].model=='Windows Computer')
            assert(created[2].label=='Windows winbox')
        ''' % (repr(path), repr(path))
        vm = lib.luaL_newstate()
        try:
            lib.luaL_openlibs(vm)
            status = lib.luaL_loadstring(vm, script.encode())
            if status == 0:
                status = lib.lua_pcallk(vm, 0, 0, 0, 0, None)
            message = lib.lua_tolstring(vm, -1, None).decode(errors='replace') if status else ''
            self.assertEqual(status, 0, message)
        finally:
            lib.lua_close(vm)


if __name__ == '__main__':
    unittest.main()
