"""Regression: discovery must not request .local hostnames from IPv6 records."""
import ctypes
from ctypes.util import find_library
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]/'edge-driver'/'src'

class DiscoveryTests(unittest.TestCase):
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
