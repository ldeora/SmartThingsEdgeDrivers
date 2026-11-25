"""Exercise power state failure classification using Lua 5.3/5.4."""
import ctypes
from lua_runtime import load_lua
from pathlib import Path
import unittest
ROOT=Path(__file__).resolve().parents[1]/'edge-driver'/'src'

class ClassifierTests(unittest.TestCase):
    def test_error_classification(self):
        lib = load_lua(self)
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
            package.path=%s .. '/?.lua;' .. package.path
            local p=require 'computerhost.presence'
            assert(p.classify_failure('HTTP transport failed: Connection refused (os error 111)')=='agent_unavailable')
            assert(p.classify_failure('[string "socket"]:1535: timeout')=='host_unreachable')
            assert(p.classify_failure('Network is unreachable')=='host_unreachable')
            assert(p.classify_failure('No route to host')=='host_unreachable')
            assert(p.classify_failure('unexpected installation ID at known address')=='unknown')
            assert(p.classify_failure('invalid JSON')=='unknown')
            assert(p.classify_failure(nil)=='unknown')
        """%repr(str(ROOT))
        vm=lib.luaL_newstate()
        try:
            lib.luaL_openlibs(vm)
            status=lib.luaL_loadstring(vm,script.encode())
            if status==0: status=lib.lua_pcallk(vm,0,0,0,0,None)
            message=lib.lua_tolstring(vm,-1,None).decode(errors='replace') if status else ''
            self.assertEqual(status,0,message)
        finally: lib.lua_close(vm)
