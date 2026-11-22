"""Mocked SmartThings Lua driver lifecycle/command state-machine tests."""
import ctypes
from ctypes.util import find_library
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]/'edge-driver'/'src'

class LuaDriverTests(unittest.TestCase):
    def test_switch_wol_shutdown_and_network_failure(self):
        libname=find_library('lua5.4') or find_library('lua5.3')
        if not libname: self.skipTest('Lua library missing')
        lib=ctypes.CDLL(libname)
        lib.luaL_newstate.restype=ctypes.c_void_p
        lib.luaL_openlibs.argtypes=[ctypes.c_void_p]
        lib.luaL_loadstring.argtypes=[ctypes.c_void_p,ctypes.c_char_p]
        lib.luaL_loadstring.restype=ctypes.c_int
        lib.lua_pcallk.argtypes=[ctypes.c_void_p,ctypes.c_int,ctypes.c_int,ctypes.c_int,ctypes.c_ssize_t,ctypes.c_void_p]
        lib.lua_pcallk.restype=ctypes.c_int
        lib.lua_tolstring.argtypes=[ctypes.c_void_p,ctypes.c_int,ctypes.c_void_p]
        lib.lua_tolstring.restype=ctypes.c_char_p
        lib.lua_close.argtypes=[ctypes.c_void_p]
        script=r'''
            package.path=%s .. '/?.lua;' .. %s .. '/?/init.lua;' .. package.path
            package.loaded['log']={info=function() end, warn=function() end, error=function() end, debug=function() end}
            package.loaded['st.driver']=function(name,template)
              _G.TEMPLATE=template
              return {run=function() end}
            end
            local sw=setmetatable({
              on=function() return {kind='switch',value='on'} end,
              off=function() return {kind='switch',value='off'} end,
            },{__call=function(_,s) return {kind='switch',value=s} end})
            package.loaded['st.capabilities']={
              switch={ID='switch',switch=sw,commands={on={NAME='on'},off={NAME='off'}}},
              refresh={ID='refresh',commands={refresh={NAME='refresh'}}},
              momentary={ID='momentary',commands={push={NAME='push'}}},
              temperatureMeasurement={temperature=function() return {kind='temperature'} end}
            }
            local healthy=true
            local error_message='HTTP transport failed: connection refused'
            local boot_id='boot-one'
            local id='aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'
            package.loaded['computerhost.api']={
              fetch_health=function()
                if not healthy then return nil,error_message end
                return {id=id,boot_id=boot_id,status='running',uptime_seconds=60}
              end,
              fetch_info=function() return {id=id,wol_mac='00:11:22:33:44:55',power_actions={'reboot','shutdown','suspend'}} end,
              fetch_metrics=function() return {id=id,cpu_temperature_c=40} end,
            }
            package.loaded['computerhost.discovery']={
              handle_discovery=function() end,
              apply_pending=function() end,
              save_fields=function(device,host,port,uuid,hostname,info)
                if host then device:set_field('computerhost_host',host) end
                if port then device:set_field('computerhost_port',port) end
                if info then device:set_field('computerhost_mac',info.wol_mac) end
              end,
              refresh_fields=function(device,host,port)
                local info=package.loaded['computerhost.api'].fetch_info(host,port)
                device:set_field('computerhost_mac',info.wol_mac)
                return info
              end,
              rediscover=function() return false,'missing' end,
            }
            package.loaded['computerhost.telemetry']={status=function(dev,status) dev.last_status=status; return true end,metrics=function() end}
            local wakes,actions=0,{}
            local action_error=nil
            local wake_failure=false
            package.loaded['computerhost.power']={
              wake=function(device)
                wakes=wakes+1
                if wake_failure then return nil,'invalid WOL MAC' end
                device:set_field('computerhost_pending_action','wake')
                device:set_field('computerhost_pending_at',os.time())
                return true
              end,
              action=function(device,action)
                if action_error then return false,action_error end
                actions[#actions+1]=action;device:set_field('computerhost_pending_action',action);device:set_field('computerhost_pending_at',os.time());return true end,
            }
            require 'init'
            local timers={}
            local thread={}
            function thread:call_with_delay(delay,fn,name)
              local timer={delay=delay,fn=fn,name=name}
              timers[name]=timer
              return timer
            end
            function thread:cancel_timer(timer) end
            local fields={computerhost_host='127.0.0.1',computerhost_port=8765}
            local device={
              device_network_id='computer-host:'..id,
              label='Linux Test Machine',
              preferences={pollInterval=30,failureThreshold=3},
              thread=thread,profile={components={main={capabilities={}}}},
              events={},
            }
            -- Mimic the Edge runtime when an unset field yields NO return values.
            -- This previously caused tonumber(device:get_field(...)) to throw.
            function device:get_field(k)
              if fields[k]==nil then return end
              return fields[k]
            end
            function device:set_field(k,v,opts) fields[k]=v end
            function device:emit_event(e) self.events[#self.events+1]=e end
            function device:online() self.marked_online=true end
            function device:offline() error('Controller must not go offline when target fails') end
            function device:supports_capability_by_id(id,component) return false end
            function device:try_update_metadata(metadata) self.metadata_update=metadata; return true end
            local driver={}
            TEMPLATE.lifecycle_handlers.init(driver,device)
            assert(device.metadata_update.profile=='computer-host-linux')
            assert(fields.computerhost_advanced_profile_update_sent==true)
            assert(timers['Computer Host health'])
            TEMPLATE.capability_handlers.switch.on(driver,device)
            assert(wakes==1)  -- not initially confirmed online
            assert(fields.computerhost_last_switch==nil) -- no optimistic ON
            timers['Computer Host health'].fn() -- health success
            assert(fields.computerhost_last_switch=='on')
            assert(fields.computerhost_success_count==1)
            assert(fields.computerhost_failures==0)
            assert(device.marked_online)
            healthy=false
            -- TCP refusal tells us the computer's network stack answered,
            -- even though the agent itself is down. Switch must remain ON.
            for i=1,4 do timers['Computer Host health'].fn() end
            assert(fields.computerhost_failures==4)
            assert(fields.computerhost_host_failures==0)
            assert(fields.computerhost_last_switch=='on')
            -- Failed WOL must restore the *last known* state, not force OFF
            -- when only the HTTP agent is refusing connections.
            wake_failure=true
            local previous_events=#device.events
            TEMPLATE.capability_handlers.switch.on(driver,device)
            assert(fields.computerhost_last_switch=='on')
            assert(#device.events==previous_events+1)
            assert(device.events[#device.events].value=='on')
            -- Real shutdown / suspend usually results in a silent timeout.
            error_message='HTTP transport failed: timeout'
            for i=1,3 do timers['Computer Host health'].fn() end
            assert(fields.computerhost_host_failures==3)
            assert(fields.computerhost_last_switch=='off')
            -- The mirror case: failed Wake must retain the known OFF state.
            previous_events=#device.events
            TEMPLATE.capability_handlers.switch.on(driver,device)
            assert(fields.computerhost_last_switch=='off')
            assert(#device.events==previous_events+1)
            assert(device.events[#device.events].value=='off')
            wake_failure=false
            -- A real switch-on command sends WOL and does not immediately
            -- report ON before the agent is actually reachable.
            TEMPLATE.capability_handlers.switch.on(driver,device)
            assert(wakes==4)
            assert(fields.computerhost_last_switch=='off')
            healthy=true
            timers['Computer Host health'].fn()
            assert(fields.computerhost_last_switch=='on')
            assert(fields.computerhost_pending_action==nil)
            assert(fields.computerhost_host_failures==0)
            -- If users disable outage-based OFF inference, stay ON.
            device.preferences.assumeOffWhenUnreachable=false
            healthy=false
            for i=1,3 do timers['Computer Host health'].fn() end
            assert(fields.computerhost_last_switch=='on')
            device.preferences.assumeOffWhenUnreachable=true
            healthy=true
            timers['Computer Host health'].fn()
            -- Reboot: a transient outage MUST NOT turn switch OFF.
            TEMPLATE.capability_handlers.momentary.push(driver,device,{component='reboot'})
            assert(actions[#actions]=='reboot')
            assert(fields.computerhost_pending_action=='reboot')
            timers['Computer Host health'].fn()
            assert(fields.computerhost_pending_action=='reboot') -- same boot ID
            healthy=false
            for i=1,3 do timers['Computer Host health'].fn() end
            assert(fields.computerhost_last_switch=='on')
            healthy=true
            boot_id='boot-two'
            timers['Computer Host health'].fn()
            assert(fields.computerhost_last_switch=='on')
            assert(fields.computerhost_pending_action==nil)
            -- A refused TCP connection is NOT proof of a finished shutdown,
            -- even after a signed/acknowledged shutdown action.
            -- An accepted OFF is acknowledged at once with a real ON->OFF
            -- change, so the app does not wait for its command timeout.
            local State=require 'computerhost.state'
            local sent_actions=#actions
            previous_events=#device.events
            TEMPLATE.capability_handlers.switch.off(driver,device)
            assert(#actions==sent_actions+1 and actions[#actions]=='shutdown')
            assert(fields.computerhost_last_switch=='off')
            assert(#device.events==previous_events+1)
            assert(device.events[#device.events].value=='off')
            assert(device.events[#device.events].state_change==nil)
            assert(device.last_status=='stopping')
            -- The agent may still answer during the grace period: the switch
            -- stays OFF and ordinary polling emits no switch event.
            previous_events=#device.events
            timers['Computer Host health'].fn()
            assert(fields.computerhost_last_switch=='off')
            assert(device.last_status=='stopping')
            assert(#device.events==previous_events)
            -- A duplicate OFF while stopping is a no-op: no second request
            -- (Windows would answer 409) and no switch transition.
            TEMPLATE.capability_handlers.switch.off(driver,device)
            assert(#actions==sent_actions+1)
            assert(fields.computerhost_last_switch=='off')
            assert(#device.events==previous_events)
            -- ON while the agent still answers must not replace the pending
            -- shutdown or send a Wake request.
            local wakes_before=wakes
            TEMPLATE.capability_handlers.switch.on(driver,device)
            assert(wakes==wakes_before)
            assert(fields.computerhost_pending_action=='shutdown')
            assert(fields.computerhost_last_switch=='off')
            -- Agent still answering after the grace period: shutdown cancelled
            -- or blocked. Host is running again and the switch returns to ON.
            fields.computerhost_pending_at=os.time()-State.SHUTDOWN_GRACE_SECONDS
            timers['Computer Host health'].fn()
            assert(device.last_status=='running')
            assert(fields.computerhost_last_switch=='on')
            assert(device.events[#device.events].value=='on')
            assert(fields.computerhost_pending_action=='shutdown') -- 180 s bound
            -- A 409 after the grace period (Windows busy, or a shutdown OR
            -- reboot in progress) is a rejection, not an accepted shutdown:
            -- switch stays ON, status stays running, pending is not renewed.
            local pending_at=fields.computerhost_pending_at
            action_error='HTTP status 409 (Windows shutdown or reboot is already in progress)'
            TEMPLATE.capability_handlers.switch.off(driver,device)
            action_error=nil
            assert(#actions==sent_actions+1)
            assert(fields.computerhost_last_switch=='on')
            assert(device.last_status=='running')
            assert(fields.computerhost_pending_at==pending_at)
            -- Once running again, a new OFF is sent even though the earlier
            -- shutdown is still recorded as pending.
            TEMPLATE.capability_handlers.switch.off(driver,device)
            assert(#actions==sent_actions+2 and actions[#actions]=='shutdown')
            assert(fields.computerhost_last_switch=='off')
            assert(device.last_status=='stopping')
            -- A different boot ID proves the computer is running again, even
            -- inside the shutdown grace period.
            local events_before_boot=#device.events
            boot_id='boot-three'
            timers['Computer Host health'].fn()
            assert(fields.computerhost_last_switch=='on')
            assert(device.last_status=='running')
            assert(fields.computerhost_pending_action==nil)
            assert(#device.events==events_before_boot+1)
            -- Start another shutdown to test a conflicting ON after the agent
            -- becomes unreachable, when the normal path would try Wake.
            TEMPLATE.capability_handlers.switch.off(driver,device)
            assert(#actions==sent_actions+3)
            assert(fields.computerhost_last_switch=='off')
            assert(fields.computerhost_pending_action=='shutdown')
            healthy=false
            error_message='HTTP transport failed: connection refused'
            timers['Computer Host health'].fn()
            assert(fields.computerhost_last_ok==false)
            wakes_before=wakes
            TEMPLATE.capability_handlers.switch.on(driver,device)
            assert(wakes==wakes_before)
            assert(fields.computerhost_pending_action=='shutdown')
            assert(fields.computerhost_last_switch=='off')
            for i=1,3 do timers['Computer Host health'].fn() end
            assert(fields.computerhost_last_switch=='off')
            assert(device.last_status=='stopping')
            assert(fields.computerhost_pending_action=='shutdown')
            -- Silent host timeouts, unlike refusal, now support OFF inference.
            error_message='HTTP transport failed: timeout'
            for i=1,3 do timers['Computer Host health'].fn() end
            assert(fields.computerhost_last_switch=='off')
            assert(device.last_status=='stopped')
            -- Fresh health response turns it back ON, even without a WOL
            -- command (e.g. manual power-on or a scheduled boot).
            healthy=true
            timers['Computer Host health'].fn()
            assert(fields.computerhost_last_switch=='on')
            -- Suspend has the same command/confirmation semantics.
            TEMPLATE.capability_handlers.momentary.push(driver,device,{component='suspend'})
            assert(actions[#actions]=='suspend')
            healthy=false
            for i=1,3 do timers['Computer Host health'].fn() end
            assert(fields.computerhost_last_switch=='off')
            assert(device.last_status=='suspended')
            -- Unexpected wrong-host responses must not count as power loss.
            healthy=true
            timers['Computer Host health'].fn()
            assert(fields.computerhost_last_switch=='on')
            healthy=false
            error_message='unexpected installation ID at known address'
            for i=1,3 do timers['Computer Host health'].fn() end
            assert(device.last_status=='unknown')
            assert(fields.computerhost_last_switch=='on')

        '''
        script=script%(repr(str(ROOT)),repr(str(ROOT)))
        vm=lib.luaL_newstate()
        try:
            lib.luaL_openlibs(vm)
            status=lib.luaL_loadstring(vm,script.encode())
            if status==0: status=lib.lua_pcallk(vm,0,0,0,0,None)
            error=lib.lua_tolstring(vm,-1,None).decode(errors='replace') if status else ''
            self.assertEqual(status,0,error)
        finally:
            lib.lua_close(vm)
