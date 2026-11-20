"""Real Lua VM test of pure Linux Host power-state classification."""
import ctypes
from ctypes.util import find_library
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]/'edge-driver'/'src'

class StateReducerTests(unittest.TestCase):
    def test_failure_and_success_transitions(self):
        libname = find_library('lua5.4') or find_library('lua5.3')
        if not libname:
            self.skipTest('Lua runtime library unavailable')
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
        script = r'''
            package.path=%s..'/?.lua;'..package.path
            local S=require 'computerhost.state'
            local a,b,c
            a,b,c=S.failure('shutdown','agent_unavailable',3,0,3,true)
            assert(a=='stopping' and b==nil and c==false)
            a,b,c=S.failure('shutdown','host_unreachable',3,3,3,true)
            assert(a=='stopped' and b=='off' and c==true)
            a,b,c=S.failure('suspend','host_unreachable',4,4,3,false)
            assert(a=='suspended' and b=='off' and c==true)
            a,b,c=S.failure('reboot','host_unreachable',4,4,3,true)
            assert(a=='rebooting' and b==nil and c==false)
            a,b,c=S.failure(nil,'agent_unavailable',3,0,3,true)
            assert(a=='unreachable' and b=='on' and c==false)
            a,b,c=S.failure(nil,'host_unreachable',3,3,3,true)
            assert(a=='unreachable' and b=='off' and c==false)
            a,b,c=S.failure(nil,'host_unreachable',3,3,3,false)
            assert(a=='unreachable' and b==nil and c==false)
            a,b,c=S.failure(nil,'unknown',3,0,3,true)
            assert(a=='unknown' and b==nil and c==false)
            a,b,c=S.failure(nil,'host_unreachable',2,2,3,true)
            assert(a==nil and b==nil and c==false)
            a,b=S.success('reboot',false)
            assert(a=='rebooting' and b==false)
            a,b=S.success('reboot',true)
            assert(a=='running' and b==true)
            a,b=S.success('wake',false)
            assert(a=='running' and b==true)
            -- Suspend accepted but still running: keep transitional state.
            a,b=S.success('suspend',false,0,10)
            assert(a=='suspending' and b==false)
            -- One transient failed poll alone is not enough to confirm a resume.
            a,b=S.success('suspend',false,1,10)
            assert(a=='suspending' and b==false)
            -- Multiple failed polls before a successful poll confirm a resume gap.
            a,b=S.success('suspend',false,2,10)
            assert(a=='running' and b==true)
            -- Expired display grace returns Running but keeps bounded pending context.
            a,b=S.success('suspend',false,0,31)
            assert(a=='running' and b==false)
            -- A cancelled shutdown should recover to Running, allowing late shutdown.
            a,b=S.success('shutdown',false,0,15)
            assert(a=='stopping' and b==false)
            a,b=S.success('shutdown',false,0,61)
            assert(a=='running' and b==false)
        ''' % repr(str(ROOT))
        vm=lib.luaL_newstate()
        try:
            lib.luaL_openlibs(vm)
            status=lib.luaL_loadstring(vm,script.encode())
            if status==0: status=lib.lua_pcallk(vm,0,0,0,0,None)
            err=lib.lua_tolstring(vm,-1,None).decode(errors='replace') if status else ''
            self.assertEqual(status,0,err)
        finally:
            lib.lua_close(vm)

if __name__=='__main__':unittest.main()
