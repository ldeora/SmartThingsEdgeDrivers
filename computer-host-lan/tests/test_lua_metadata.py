"""Exercise real discovery + WOL modules with a mocked Edge device and network."""
import ctypes
from lua_runtime import load_lua
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1] / 'edge-driver' / 'src'

class MetadataRecoveryTests(unittest.TestCase):
    def test_wol_recovery_uses_matching_agent_uuid_and_persists_mac(self):
        lib = load_lua(self)
        lib.luaL_newstate.restype = ctypes.c_void_p
        lib.luaL_openlibs.argtypes = [ctypes.c_void_p]
        lib.luaL_loadstring.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
        lib.luaL_loadstring.restype = ctypes.c_int
        lib.lua_pcallk.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_ssize_t, ctypes.c_void_p]
        lib.lua_pcallk.restype = ctypes.c_int
        lib.lua_tolstring.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p]
        lib.lua_tolstring.restype = ctypes.c_char_p
        lib.lua_close.argtypes = [ctypes.c_void_p]
        script = r'''
            package.path = %s .. '/?.lua;' .. %s .. '/?/init.lua;' .. package.path
            local log_messages={}
            package.loaded['log']={
              info=function(s) log_messages[#log_messages+1]=s end,
              warn=function(s) log_messages[#log_messages+1]=s end,
              error=function(s) log_messages[#log_messages+1]=s end,
            }
            package.loaded['st.mdns']={discover=function() return {found={}} end}
            local sent={}
            package.loaded['cosock']={socket={udp=function()
              return {
                settimeout=function() end,
                setoption=function(_,k,v) assert(k=='broadcast' and v); return 1 end,
                sendto=function(_,packet,host,port)
                  assert(#packet==102)
                  sent[#sent+1]={host=host,port=port}
                  return #packet
                end,
                close=function() end,
              }
            end}}
            local valid='11111111-2222-4333-8444-555555555555'
            local info={id=valid,wol_mac='02:42:ac:11:00:05',
              wol_broadcast='192.168.50.255',hostname='examplehost',power_actions={'shutdown'}}
            local api_calls=0
            package.loaded['computerhost.api']={fetch_info=function(host,port)
              api_calls=api_calls+1
              assert(host=='192.168.50.123')
              assert(port==8765)
              if not info then return nil,'connection refused' end
              return info
            end}
            local C=require 'computerhost.constants'
            local D=require 'computerhost.discovery'
            local Power=require 'computerhost.power'
            local fields={[C.FIELD_HOST]='192.168.50.123',[C.FIELD_PORT]=8765}
            local persisted={}
            local dev={device_network_id='computer-host:'..valid,label='Linux examplehost',preferences={}}
            function dev:get_field(key)
              if fields[key]==nil then return end -- Edge can return zero values
              return fields[key]
            end
            function dev:set_field(key,value,opts)
              fields[key]=value
              if opts and opts.persist then persisted[key]=value end
            end
            -- Newly-created device has address but NO stored WOL metadata.
            assert(fields[C.FIELD_MAC]==nil)
            assert(Power.wake(dev))
            assert(api_calls==1)
            assert(fields[C.FIELD_MAC]=='02:42:ac:11:00:05')
            assert(persisted[C.FIELD_MAC]=='02:42:ac:11:00:05')
            assert(persisted[C.FIELD_BROADCAST]=='192.168.50.255')
            assert(#sent==3 and sent[1].host=='192.168.50.255' and sent[1].port==9)
            -- Once metadata has been cached, sending WOL must work with host OFF.
            info=nil
            local before=api_calls
            assert(Power.wake(dev))
            assert(api_calls==before)
            assert(#sent==6)
            -- A recycled DHCP address belonging to a different Linux agent
            -- must NEVER be allowed to supply our WOL MAC.
            fields[C.FIELD_MAC]=nil
            info={id='aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
              wol_mac='00:11:22:33:44:55',wol_broadcast='192.168.50.255'}
            local ok,err=Power.wake(dev)
            assert(not ok and err:find('WOL MAC unavailable',1,true))
            assert(fields[C.FIELD_MAC]==nil)
            assert(#sent==6)
            -- Explicit override works while agent is offline.
            info=nil
            dev.preferences.wolMacOverride='02:42:ac:11:00:05'
            assert(Power.wake(dev))
            assert(#sent==9)
            -- Invalid override should be rejected instead of silently replaced.
            dev.preferences.wolMacOverride='ff:ff:ff:ff:ff:ff'
            ok,err=Power.wake(dev)
            assert(not ok and err:find('override is invalid',1,true))
            assert(#sent==9)
            -- Power actions: the Windows agent answers 409 both when its
            -- dispatcher is busy (e.g. a pending suspend) and for
            -- ERROR_SHUTDOWN_IN_PROGRESS, which also covers a reboot. A 409
            -- is therefore never an accepted shutdown and records nothing.
            dev.preferences.allowPowerCommands=true
            dev.preferences.controlKey=string.rep('a',64)
            fields[C.FIELD_POWER_ACTIONS]='reboot,shutdown,suspend'
            local control_result
            package.loaded['computerhost.api'].control=function()
              return control_result[1],control_result[2]
            end
            for _,reason in ipairs({
              'HTTP status 409 (power operation already pending)',
              'HTTP status 409 (Windows shutdown or reboot is already in progress)',
              'HTTP status 503 (Service Unavailable)'}) do
              control_result={nil,reason}
              fields[C.FIELD_PENDING_ACTION]=nil
              ok,err=Power.action(dev,'shutdown')
              assert(not ok and err==reason)
              assert(fields[C.FIELD_PENDING_ACTION]==nil)
            end
            control_result={true,nil}
            assert(Power.action(dev,'shutdown')==true)
            assert(fields[C.FIELD_PENDING_ACTION]=='shutdown')
        ''' % (repr(str(ROOT)),repr(str(ROOT)))
        state = lib.luaL_newstate()
        try:
            lib.luaL_openlibs(state)
            rc = lib.luaL_loadstring(state, script.encode())
            if rc == 0:
                rc = lib.lua_pcallk(state, 0, 0, 0, 0, None)
            msg = lib.lua_tolstring(state, -1, None).decode(errors='replace') if rc else ''
            self.assertEqual(rc, 0, msg)
        finally:
            lib.lua_close(state)

if __name__ == '__main__':
    unittest.main()
