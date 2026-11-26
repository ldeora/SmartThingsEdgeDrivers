"""Conservative known-endpoint selection and delayed metadata promotion."""
import ctypes
from pathlib import Path
import unittest
from lua_runtime import load_lua

ROOT = Path(__file__).resolve().parents[1] / 'edge-driver' / 'src'


class DiscoveryMigrationTests(unittest.TestCase):
    def test_selection_override_migration_and_health_confirmation(self):
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
        script = r"""
          package.path=%s .. '/?.lua;' .. %s .. '/?/init.lua;' .. package.path
          local id='aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'
          local other='bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb'
          local a,b='192.0.2.10','192.0.2.20'
          local oldmac,newmac='02:11:22:33:44:55','02:aa:bb:cc:dd:ee'
          local logs={}
          package.loaded['log']={info=function(x) logs[#logs+1]=x end,
            warn=function() end,error=function(x) error(x) end,debug=function() end}
          package.loaded['st.mdns']={discover=function() return {found={}} end}
          local infos={
            [a]={id=id,hostname='old',platform='linux',wol_mac=oldmac,
              wol_broadcast='192.0.2.255',power_actions={'shutdown'}},
            [b]={id=id,hostname='new',platform='linux',wol_mac=newmac,
              wol_broadcast='198.51.100.255',power_actions={'reboot'}}
          }
          local healths={[a]=id,[b]=id}
          local health_calls,info_calls=0,0
          local on_health,on_info
          local API={
            fetch_health=function(host,port)
              health_calls=health_calls+1
              if on_health then on_health(host,port) end
              return healths[host] and {id=healths[host],status='running',boot_id='boot'} or nil,'timeout'
            end,
            fetch_info=function(host,port)
              info_calls=info_calls+1
              if on_info then on_info(host,port) end
              return infos[host]
            end,
            fetch_metrics=function(host) return {id=id} end
          }
          package.loaded['computerhost.api']=API
          local C=require 'computerhost.constants'
          local D=require 'computerhost.discovery'
          local fields={[C.FIELD_HOST]=a,[C.FIELD_PORT]=8765,[C.FIELD_UUID]=id,
            [C.FIELD_MAC]=oldmac,[C.FIELD_BROADCAST]='192.0.2.255',
            [C.FIELD_NAME]='old',[C.FIELD_POWER_ACTIONS]='shutdown',[C.FIELD_LAST_OK]=true,
            computerhost_success_count=6}
          local persisted={}
          local dev={device_network_id=C.DNI_PREFIX..id,preferences={},label='fixture'}
          function dev:get_field(k) if fields[k]==nil then return end; return fields[k] end
          function dev:set_field(k,v,opts)
            fields[k]=v
            if opts and opts.persist then persisted[k]=v==nil and false or v end
          end
          function dev:online() end
          function dev:emit_event() end
          function dev:supports_capability_by_id() return true end
          local driver={get_devices=function() return {dev} end}
          local candidate={host=b,port=9876}
          D.candidates=function() return {{host=a,port=8765},candidate} end
          local function old_endpoint()
            assert(fields[C.FIELD_HOST]==a and fields[C.FIELD_PORT]==8765)
            assert(fields[C.FIELD_MAC]==oldmac and fields[C.FIELD_BROADCAST]=='192.0.2.255')
            assert(fields[C.FIELD_POWER_ACTIONS]=='shutdown')
          end
          -- Both scan orders and recovery scans prefer a responsive known endpoint.
          assert(D.process_candidate(driver,candidate)==dev); old_endpoint()
          assert(D.process_candidate(driver,{host=a,port=8765})==dev); old_endpoint()
          assert(D.process_candidate(driver,candidate)==dev); old_endpoint()
          assert(D.rediscover(driver,dev)); old_endpoint()
          -- A different port on the same IP is also a competing endpoint.
          on_health=function(host,port) assert(host==a and port==8765) end
          assert(D.process_candidate(driver,{host=a,port=9876})==dev); old_endpoint()
          on_health=nil
          -- Override without explicit port must not be silently retargeted.
          dev.preferences.hostOverride=b
          local hc=health_calls
          assert(D.process_candidate(driver,candidate)==dev); old_endpoint()
          assert(not D.rediscover(driver,dev)); old_endpoint()
          assert(health_calls==hc)
          assert(not D.refresh_fields(dev,a,8765))
          assert(D.refresh_fields(dev,b,8765))
          assert(fields[C.FIELD_HOST]==a and fields[C.FIELD_PORT]==8765)
          assert(fields[C.FIELD_MAC]==newmac)
          dev.preferences.hostOverride=nil
          D.save_fields(dev,a,8765,id,'old',infos[a]); old_endpoint()
          -- A health probe yielding to a successful poll must not commit stale failure.
          healths[a]=nil
          on_health=function() fields.computerhost_success_count=7 end
          assert(D.process_candidate(driver,candidate)==dev); old_endpoint()
          on_health=nil
          fields[C.FIELD_IN_PROGRESS]=true
          assert(D.process_candidate(driver,candidate)==dev); old_endpoint()
          fields[C.FIELD_IN_PROGRESS]=false
          -- Actual power code holds selection stable across a yielding request.
          package.loaded['computerhost.wol']={send=function() error('unexpected WOL') end}
          local Power=require 'computerhost.power'
          dev.preferences.allowPowerCommands=true
          dev.preferences.controlKey=string.rep('a',64)
          local power_calls=0
          API.control=function(host,port)
            power_calls=power_calls+1
            assert(host==a and port==8765 and fields[C.FIELD_POWER_BUSY])
            assert(D.process_candidate(driver,candidate)==dev); old_endpoint()
            return nil,'refused',403
          end
          local ok,err,status=Power.action(dev,'shutdown')
          assert(not ok and err=='refused' and status==403 and power_calls==1)
          assert(not fields[C.FIELD_POWER_BUSY])
          API.control=function() error('simulated transport exception') end
          assert(not pcall(Power.action,dev,'shutdown'))
          assert(not fields[C.FIELD_POWER_BUSY])
          API.control=function() power_calls=power_calls+1; error('unconfirmed endpoint contacted') end
          -- Wrong UUID at the old address permits real migration; metadata is retained.
          healths[a]=other
          assert(D.process_candidate(driver,candidate)==dev)
          assert(fields[C.FIELD_HOST]==b and fields[C.FIELD_PORT]==9876)
          assert(fields[C.FIELD_ENDPOINT_UNCONFIRMED] and persisted[C.FIELD_ENDPOINT_UNCONFIRMED])
          assert(not fields[C.FIELD_LAST_OK])
          assert(fields[C.FIELD_MAC]==oldmac and fields[C.FIELD_POWER_ACTIONS]=='shutdown')
          assert(D.process_candidate(driver,candidate)==dev)
          assert(fields[C.FIELD_MAC]==oldmac and fields[C.FIELD_NAME]=='old')
          local rejected,reason=Power.action(dev,'shutdown')
          assert(not rejected and reason:find('not yet confirmed',1,true))
          assert(power_calls==1 and not fields[C.FIELD_POWER_BUSY])
          local ic=info_calls
          assert(not D.refresh_fields(dev,b,9876)); assert(info_calls==ic)
          -- Real init/poll, including a failed matching-ID check and subsequent recovery.
          local template
          package.loaded['st.driver']=function(_,t) template=t; return {run=function() end} end
          package.loaded['st.capabilities']={
            switch={ID='switch',commands={on={NAME='on'},off={NAME='off'}},switch=function(v) return v end},
            refresh={ID='refresh',commands={refresh={NAME='refresh'}}},
            momentary={ID='momentary',commands={push={NAME='push'}}}}
          package.loaded['computerhost.telemetry']={status=function() return true end,metrics=function() end}
          local timers={}
          dev.thread={call_with_delay=function(_,_,fn,name) timers[name]=fn;return fn end,
            cancel_timer=function() end}
          require 'init'
          template.lifecycle_handlers.init(driver,dev)
          healths[b]=other
          template.capability_handlers.refresh.refresh(driver,dev)
          assert(fields[C.FIELD_ENDPOINT_UNCONFIRMED] and fields[C.FIELD_MAC]==oldmac)
          healths[b]=id
          template.capability_handlers.refresh.refresh(driver,dev)
          assert(not fields[C.FIELD_ENDPOINT_UNCONFIRMED])
          assert(fields[C.FIELD_LAST_OK] and fields[C.FIELD_MAC]==newmac and fields[C.FIELD_NAME]=='new')
          assert(fields[C.FIELD_BROADCAST]=='198.51.100.255' and fields[C.FIELD_POWER_ACTIONS]=='reboot')
          -- Rediscovery after failure follows the same guard, including port changes.
          healths[b]=nil; healths[a]=id
          assert(D.rediscover(driver,dev))
          assert(fields[C.FIELD_HOST]==a and fields[C.FIELD_PORT]==8765)
          assert(fields[C.FIELD_ENDPOINT_UNCONFIRMED] and fields[C.FIELD_MAC]==newmac)
          template.capability_handlers.refresh.refresh(driver,dev)
          old_endpoint()
          assert(not fields[C.FIELD_ENDPOINT_UNCONFIRMED])
          -- The fifth failed real poll must not probe the failed endpoint twice.
          healths[a]=nil; healths[b]=id
          fields[C.FIELD_FAILURES]=C.REDISCOVERY_EVERY_FAILURES-1
          hc=health_calls
          template.capability_handlers.refresh.refresh(driver,dev)
          assert(health_calls==hc+1,'redundant failed health probe')
          assert(fields[C.FIELD_HOST]==b and fields[C.FIELD_ENDPOINT_UNCONFIRMED])
          assert(fields[C.FIELD_MAC]==oldmac)
          template.capability_handlers.refresh.refresh(driver,dev)
          assert(not fields[C.FIELD_ENDPOINT_UNCONFIRMED])
          healths[b]=nil; healths[a]=id
          assert(D.rediscover(driver,dev))
          template.capability_handlers.refresh.refresh(driver,dev)
          old_endpoint()
          -- Stale info from a previously effective endpoint must not change metadata.
          on_info=function() dev.preferences.hostOverride=b..':9876' end
          assert(not D.refresh_fields(dev,a,8765)); old_endpoint()
          on_info=nil
          -- Polling a manual override must not rewrite the automatic host/port.
          healths[b]=id
          template.capability_handlers.refresh.refresh(driver,dev)
          assert(fields[C.FIELD_HOST]==a and fields[C.FIELD_PORT]==8765)
          for _,line in ipairs(logs) do
            assert(not line:find(a,1,true) and not line:find(b,1,true),'address leaked in info log')
          end
        """ % (repr(str(ROOT)), repr(str(ROOT)))
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
