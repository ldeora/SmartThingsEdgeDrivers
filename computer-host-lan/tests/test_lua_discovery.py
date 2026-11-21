"""Regression: discovery must not request .local hostnames from IPv6 records."""
import ctypes
from ctypes.util import find_library
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]/'edge-driver'/'src'

class DiscoveryTests(unittest.TestCase):
    def test_silent_create_drop_retries_only_after_ttl(self):
        """A dropped try_create_device must not permanently suppress scans."""
        name=find_library('lua5.4') or find_library('lua5.3')
        if not name: self.skipTest('Lua library unavailable')
        lib=ctypes.CDLL(name)
        lib.luaL_newstate.restype=ctypes.c_void_p
        lib.luaL_openlibs.argtypes=[ctypes.c_void_p]
        lib.luaL_loadstring.argtypes=[ctypes.c_void_p,ctypes.c_char_p]
        lib.luaL_loadstring.restype=ctypes.c_int
        lib.lua_pcallk.argtypes=[ctypes.c_void_p,ctypes.c_int,ctypes.c_int,ctypes.c_int,ctypes.c_ssize_t,ctypes.c_void_p]
        lib.lua_pcallk.restype=ctypes.c_int
        lib.lua_tolstring.argtypes=[ctypes.c_void_p,ctypes.c_int,ctypes.c_void_p]
        lib.lua_tolstring.restype=ctypes.c_char_p
        lib.lua_close.argtypes=[ctypes.c_void_p]
        script=r"""
          package.path=%s .. '/?.lua;' .. %s .. '/?/init.lua;' .. package.path
          package.loaded['log']={info=function() end,warn=function() end}
          package.loaded['st.mdns']={discover=function() return {found={}} end}
          local id='aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'
          local now=1000
          os.time=function() return now end
          local info={id=id,hostname='Retry Host',platform='linux'}
          package.loaded['computerhost.api']={fetch_info=function() return info,nil end}
          local D=require 'computerhost.discovery'
          local C=require 'computerhost.constants'
          local dni=C.DNI_PREFIX..id
          local creates=0
          local devices={}
          local driver={
            get_devices=function() return devices end,
            try_create_device=function(self,data)
              assert(data.device_network_id==dni)
              creates=creates+1
              -- Simulate hub silently dropping this request (no exception).
            end
          }
          local candidate={host='127.0.0.1',port=8765}
          D.process_candidate(driver,candidate)
          assert(creates==1)
          now=1119
          D.process_candidate(driver,candidate)
          assert(creates==1,'Unconfirmed create request duplicated within TTL')
          now=1120
          D.process_candidate(driver,candidate)
          assert(creates==2,'Silently dropped request was never retried')
          now=1121
          D.process_candidate(driver,candidate)
          assert(creates==2,'Duplicate retry before next TTL')
          local fields={}
          local device={device_network_id=dni,
            set_field=function(self,k,v) fields[k]=v end,
            get_field=function(self,k) return fields[k] end}
          assert(D.apply_pending(device),'Late created device must receive pending metadata')
          assert(fields[C.FIELD_HOST]=='127.0.0.1')
          devices[1]=device
          now=1400
          local found,err=D.process_candidate(driver,candidate)
          assert(found==device and err==nil,'Existing UUID must never be re-created')
          assert(creates==2)
        """%(repr(str(ROOT)),repr(str(ROOT)))
        vm=lib.luaL_newstate()
        try:
            lib.luaL_openlibs(vm)
            status=lib.luaL_loadstring(vm,script.encode())
            if status==0: status=lib.lua_pcallk(vm,0,0,0,0,None)
            message=lib.lua_tolstring(vm,-1,None).decode(errors='replace') if status else ''
            self.assertEqual(status,0,message)
        finally:
            lib.lua_close(vm)

    def test_ipv4_preferred_and_ipv6_hostname_fallback_skipped(self):
        name=find_library('lua5.4') or find_library('lua5.3')
        if not name: self.skipTest('Lua library unavailable')
        lib=ctypes.CDLL(name)
        lib.luaL_newstate.restype=ctypes.c_void_p
        lib.luaL_openlibs.argtypes=[ctypes.c_void_p]
        lib.luaL_loadstring.argtypes=[ctypes.c_void_p,ctypes.c_char_p]
        lib.luaL_loadstring.restype=ctypes.c_int
        lib.lua_pcallk.argtypes=[ctypes.c_void_p,ctypes.c_int,ctypes.c_int,ctypes.c_int,ctypes.c_ssize_t,ctypes.c_void_p]
        lib.lua_pcallk.restype=ctypes.c_int
        lib.lua_tolstring.argtypes=[ctypes.c_void_p,ctypes.c_int,ctypes.c_void_p]
        lib.lua_tolstring.restype=ctypes.c_char_p
        lib.lua_close.argtypes=[ctypes.c_void_p]
        script=r"""
          package.path=%s .. '/?.lua;' .. %s .. '/?/init.lua;' .. package.path
          package.loaded['log']={info=function() end,warn=function() end}
          package.loaded['st.mdns']={discover=function()
            return { found={
              {service_info={name='_computerhost._tcp'}, host_info={address='2a02:3032::1234',name='examplehost-2.local',port=8765}},
              {service_info={name='_computerhost._tcp'}, host_info={address='192.168.50.123',name='examplehost-2.local',port=8765}},
              {service_info={name='_computerhost._tcp'}, host_info={address='192.168.50.123',name='examplehost-2.local',port=8765}},
            }}
          end}
          package.loaded['computerhost.api']={}
          local D=require 'computerhost.discovery'
          local candidates=D.candidates()
          assert(#candidates==1,'Expected one IPv4 LAN candidate, got '..#candidates)
          assert(candidates[1].host=='192.168.50.123')
          assert(candidates[1].port==8765)
        """%(repr(str(ROOT)),repr(str(ROOT)))
        vm=lib.luaL_newstate()
        try:
            lib.luaL_openlibs(vm)
            status=lib.luaL_loadstring(vm,script.encode())
            if status==0: status=lib.lua_pcallk(vm,0,0,0,0,None)
            message=lib.lua_tolstring(vm,-1,None).decode(errors='replace') if status else ''
            self.assertEqual(status,0,message)
        finally:
            lib.lua_close(vm)
