"""Syntax check without a Lua CLI, using liblua's parser if available."""
import ctypes
from ctypes.util import find_library
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1] / "edge-driver" / "src"


class LuaSyntaxTests(unittest.TestCase):
    def test_all_lua_files_parse(self):
        libpath = find_library("lua5.3") or find_library("lua5.4")
        if not libpath:
            self.skipTest("Lua runtime library unavailable")
        lib = ctypes.CDLL(libpath)
        lib.luaL_newstate.restype = ctypes.c_void_p
        lib.luaL_loadfilex.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_char_p]
        lib.luaL_loadfilex.restype = ctypes.c_int
        lib.lua_tolstring.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p]
        lib.lua_tolstring.restype = ctypes.c_char_p
        lib.lua_close.argtypes = [ctypes.c_void_p]
        for path in sorted(ROOT.rglob("*.lua")):
            with self.subTest(path=str(path.relative_to(ROOT))):
                vm = lib.luaL_newstate()
                try:
                    status = lib.luaL_loadfilex(vm, str(path).encode(), None)
                    message = ""
                    if status:
                        message = lib.lua_tolstring(vm, -1, None).decode(errors="replace")
                    self.assertEqual(status, 0, message)
                finally:
                    lib.lua_close(vm)
