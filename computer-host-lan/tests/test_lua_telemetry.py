"""Exercise the custom SmartThings telemetry events and update thresholds."""
import ctypes
from lua_runtime import load_lua
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1] / 'edge-driver' / 'src'


class LuaTelemetryTests(unittest.TestCase):
    def test_custom_metrics_status_formatting_and_visibility(self):
        lib = load_lua(self)
        lib.luaL_newstate.restype = ctypes.c_void_p
        lib.luaL_openlibs.argtypes = [ctypes.c_void_p]
        lib.luaL_loadstring.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
        lib.luaL_loadstring.restype = ctypes.c_int
        lib.lua_pcallk.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int,
                                   ctypes.c_int, ctypes.c_ssize_t, ctypes.c_void_p]
        lib.lua_pcallk.restype = ctypes.c_int
        lib.lua_tolstring.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p]
        lib.lua_tolstring.restype = ctypes.c_char_p
        lib.lua_close.argtypes = [ctypes.c_void_p]

        script = r'''
            package.path=%s .. '/?.lua;' .. %s .. '/?/init.lua;' .. package.path
            package.loaded.log={warn=function() end,info=function() end,error=function() end}
            local capabilities={}
            local function cap(id,attributes)
              capabilities[id]={}
              for _,attribute in ipairs(attributes) do
                -- Real Edge attribute descriptors are callable tables.
                -- A function-only guard incorrectly rejected all of them.
                capabilities[id][attribute]=setmetatable({},{__call=function(_,value,metadata)
                  return {capability=id,attribute=attribute,value=value,metadata=metadata}
                end})
              end
            end
            cap('oceancircle09600.computerHostStatus',{'status'})
            cap('oceancircle09600.computerCpuUsage',{'cpuUsage'})
            cap('oceancircle09600.computerMemoryUsage',{'memoryUsage','memoryTotalGiB','memoryUsedGiB','memoryAvailableGiB'})
            cap('oceancircle09600.computerDiskUsage',{'diskUsage','diskTotalGiB','diskUsedGiB','diskAvailableGiB'})
            cap('oceancircle09600.computerUptime',{'uptimeMinutes','uptimeText'})
            cap('oceancircle09600.linuxLoad',{'loadOne','loadFive','loadFifteen'})
            capabilities.temperatureMeasurement={
              temperature=function(value)
                return {capability='temperatureMeasurement',attribute='temperature',value=value}
              end,
              temperatureRange=function(value)
                return {capability='temperatureMeasurement',attribute='temperatureRange',value=value}
              end,
            }
            package.loaded['st.capabilities']=capabilities
            local T=require 'computerhost.telemetry'
            local fields={}
            local device={events={}}
            function device:supports_capability_by_id(id,component)
              return component=='main' and capabilities[id]~=nil
            end
            function device:get_field(key) return fields[key] end
            function device:set_field(key,value) fields[key]=value end
            function device:emit_event(event) self.events[#self.events+1]=event end

            T.status(device,'running')
            assert(#device.events==1)
            assert(device.events[1].attribute=='status' and device.events[1].value=='running')
            assert(device.events[1].metadata==nil) -- status remains visible in history

            T.metrics(device,{
              cpu_temperature_c=48.6,
              cpu_usage_percent=17.4,
              memory_usage_percent=32.1,
              memory_total_bytes=32*1024*1024*1024,
              memory_used_bytes=10*1024*1024*1024,
              memory_available_bytes=22*1024*1024*1024,
              disk_root_usage_percent=63.0,
              disk_root_total_bytes=500*1024*1024*1024,
              disk_root_used_bytes=310*1024*1024*1024,
              disk_root_available_bytes=185*1024*1024*1024,
              load_1m=0.55,load_5m=0.70,load_15m=0.81,
              uptime_seconds=2*86400+3*3600+4*60+59,
            })
            assert(#device.events==17)
            assert(device.events[2].attribute=='temperatureRange') -- metadata first
            assert(device.events[3].attribute=='temperature') -- normal reading unchanged
            local seen={}
            for _,event in ipairs(device.events) do
              seen[(event.capability or '')..'.'..(event.attribute or '')]=event
            end
            assert(seen['temperatureMeasurement.temperature'].value.value==48.6)
            local range=seen['temperatureMeasurement.temperatureRange'].value
            assert(range.value.minimum==-40 and range.value.maximum==150)
            assert(range.unit=='C')
            assert(fields.computerhost_cpu_temperature_range_sent==true)
            assert(seen['oceancircle09600.computerCpuUsage.cpuUsage'].value==17.4)
            assert(seen['oceancircle09600.computerMemoryUsage.memoryUsage'].value==32.1)
            assert(seen['oceancircle09600.computerMemoryUsage.memoryTotalGiB'].value==32.0)
            assert(seen['oceancircle09600.computerMemoryUsage.memoryUsedGiB'].value==10.0)
            assert(seen['oceancircle09600.computerMemoryUsage.memoryAvailableGiB'].value==22.0)
            assert(seen['oceancircle09600.computerDiskUsage.diskUsage'].value==63.0)
            assert(seen['oceancircle09600.computerDiskUsage.diskTotalGiB'].value==500.0)
            assert(seen['oceancircle09600.computerDiskUsage.diskUsedGiB'].value==310.0)
            assert(seen['oceancircle09600.computerDiskUsage.diskAvailableGiB'].value==185.0)
            assert(seen['oceancircle09600.computerDiskUsage.diskTotalGiB'].metadata.visibility.displayed==false)
            assert(seen['oceancircle09600.computerDiskUsage.diskAvailableGiB'].metadata.visibility.displayed==false)
            assert(seen['oceancircle09600.computerMemoryUsage.memoryUsedGiB'].metadata.visibility.displayed==false)
            assert(seen['oceancircle09600.linuxLoad.loadOne'].value==0.55)
            assert(seen['oceancircle09600.linuxLoad.loadFive'].value==0.70)
            assert(seen['oceancircle09600.linuxLoad.loadFifteen'].value==0.81)
            assert(seen['oceancircle09600.computerUptime.uptimeMinutes'].value==3064)
            assert(seen['oceancircle09600.computerUptime.uptimeText'].value=='2d 3h')
            assert(seen['oceancircle09600.computerCpuUsage.cpuUsage'].metadata.visibility.displayed==false)
            assert(seen['oceancircle09600.computerUptime.uptimeText'].metadata.visibility.displayed==false)

            local before=#device.events
            -- Values below thresholds should not flood the hub with events.
            T.metrics(device,{
              cpu_temperature_c=48.8,cpu_usage_percent=17.7,
              memory_usage_percent=32.3,memory_total_bytes=32*1024*1024*1024,
              disk_root_usage_percent=63.2,load_1m=0.56,load_5m=0.71,load_15m=0.82,
              uptime_seconds=2*86400+3*3600+4*60+59,
            })
            assert(#device.events==before)

            -- Null and out-of-range metrics are ignored rather than emitted.
            T.metrics(device,{cpu_usage_percent=101,memory_usage_percent=-1,
              disk_root_usage_percent=101,load_1m=-0.1,uptime_seconds=-1})
            assert(#device.events==before)

            -- With day-level uptime, minute changes do not generate extra
            -- text events, but the numeric minutes still advance as usual.
            local before_text=#device.events
            T.metrics(device,{uptime_seconds=2*86400+3*3600+5*60})
            assert(#device.events==before_text)
            T.metrics(device,{uptime_seconds=2*86400+4*3600})
            assert(device.events[#device.events].attribute=='uptimeText')
            assert(device.events[#device.events].value=='2d 4h')

            -- If a capability attribute is temporarily unavailable, the
            -- driver must RETRY unchanged metrics after it becomes available.
            -- Installed RAM rarely changes, making this a useful regression.
            local mem=capabilities['oceancircle09600.computerMemoryUsage']
            local old_constructor=mem.memoryTotalGiB
            mem.memoryTotalGiB=nil
            local count=#device.events
            T.metrics(device,{memory_total_bytes=64*1024*1024*1024})
            assert(#device.events==count)
            mem.memoryTotalGiB=old_constructor
            T.metrics(device,{memory_total_bytes=64*1024*1024*1024})
            assert(#device.events==count+1)
            assert(device.events[#device.events].value==64.0)

            -- If the capacity capability is not ready yet, retry an unchanged
            -- volume size on the next poll without affecting disk percentage.
            local disk=capabilities['oceancircle09600.computerDiskUsage']
            local old_disk_total=disk.diskTotalGiB
            disk.diskTotalGiB=nil
            local disk_before=#device.events
            T.metrics(device,{disk_root_total_bytes=750*1024*1024*1024})
            assert(#device.events==disk_before)
            disk.diskTotalGiB=old_disk_total
            T.metrics(device,{disk_root_total_bytes=750*1024*1024*1024})
            assert(#device.events==disk_before+1)
            assert(device.events[#device.events].value==750.0)
            -- A temporarily unavailable new attribute must retry unchanged
            -- data; zero available GiB is valid for a full filesystem.
            local old_available=disk.diskAvailableGiB
            disk.diskAvailableGiB=nil
            local count_before=#device.events
            T.metrics(device,{disk_root_available_bytes=0})
            assert(#device.events==count_before)
            disk.diskAvailableGiB=old_available
            T.metrics(device,{disk_root_available_bytes=0})
            assert(#device.events==count_before+1)
            assert(device.events[#device.events].attribute=='diskAvailableGiB')
            assert(device.events[#device.events].value==0)
            local invalid_count=#device.events
            T.metrics(device,{disk_root_used_bytes=-1,memory_available_bytes=-1})
            assert(#device.events==invalid_count)
            -- Existing agents without the optional disk_total field must work.
            local legacy_before=#device.events
            T.metrics(device,{disk_root_usage_percent=42.0})
            assert(#device.events==legacy_before+1)
            assert(device.events[#device.events].attribute=='diskUsage')

            -- A transient missing range attribute must not interrupt readings.
            -- On a later poll, retry metadata without duplicating temperature.
            fields.computerhost_cpu_temperature_range_sent=nil
            local standard=capabilities.temperatureMeasurement
            local range_constructor=standard.temperatureRange
            standard.temperatureRange=nil
            local before_retry=#device.events
            T.metrics(device,{cpu_temperature_c=68.0})
            assert(#device.events==before_retry+1)
            assert(device.events[#device.events].attribute=='temperature')
            assert(fields.computerhost_cpu_temperature_range_sent==nil)
            standard.temperatureRange=range_constructor
            T.metrics(device,{cpu_temperature_c=68.0})
            assert(#device.events==before_retry+2)
            assert(device.events[#device.events].attribute=='temperatureRange')
            assert(fields.computerhost_cpu_temperature_range_sent==true)

            -- Without a CPU-temperature value there is no range event.
            fields.computerhost_cpu_temperature_range_sent=nil
            local without_temperature=#device.events
            T.metrics(device,{cpu_usage_percent=50.0})
            assert(#device.events==without_temperature+1) -- CPU usage only
            assert(fields.computerhost_cpu_temperature_range_sent==nil)
        ''' % (repr(str(ROOT)), repr(str(ROOT)))

        state = lib.luaL_newstate()
        try:
            lib.luaL_openlibs(state)
            rc = lib.luaL_loadstring(state, script.encode())
            if rc == 0:
                rc = lib.lua_pcallk(state, 0, 0, 0, 0, None)
            message = lib.lua_tolstring(state, -1, None).decode(errors='replace') if rc else ''
            self.assertEqual(rc, 0, message)
        finally:
            lib.lua_close(state)


if __name__ == '__main__':
    unittest.main()
