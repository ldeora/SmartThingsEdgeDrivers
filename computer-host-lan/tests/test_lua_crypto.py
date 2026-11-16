"""Execute pure-Lua SHA256/HMAC and WOL vector tests with a system Lua library."""
import ctypes
from ctypes.util import find_library
from pathlib import Path
import unittest
ROOT = Path(__file__).resolve().parents[1] / 'edge-driver' / 'src'

class LuaTests(unittest.TestCase):
    def test_crypto_and_wol_vectors(self):
        library = find_library('lua5.3') or find_library('lua5.4')
        if not library:
            self.skipTest('No Lua library installed')
        lib = ctypes.CDLL(library)
        lib.luaL_newstate.restype = ctypes.c_void_p
        lib.luaL_openlibs.argtypes=[ctypes.c_void_p]
        lib.luaL_loadstring.argtypes=[ctypes.c_void_p,ctypes.c_char_p]
        lib.luaL_loadstring.restype=ctypes.c_int
        lib.lua_pcallk.argtypes=[ctypes.c_void_p,ctypes.c_int,ctypes.c_int,ctypes.c_int,ctypes.c_ssize_t,ctypes.c_void_p]
        lib.lua_pcallk.restype=ctypes.c_int
        lib.lua_tolstring.argtypes=[ctypes.c_void_p,ctypes.c_int,ctypes.c_void_p]
        lib.lua_tolstring.restype=ctypes.c_char_p
        lib.lua_close.argtypes=[ctypes.c_void_p]
        vm=lib.luaL_newstate()
        try:
            lib.luaL_openlibs(vm)
            code=r'''
                package.path = %s .. '/?.lua;' .. %s .. '/?/init.lua;' .. package.path
                local sha=require 'computerhost.sha256'
                assert(sha.hex(sha.digest('abc')) == 'ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad')
                assert(sha.hex(sha.digest('')) == 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855')
                assert(sha.hmac_hex(string.rep('01',32), 'POST\n/v2/power/reboot\n' .. string.rep('a',48) .. '\n') ==
                       'EXPECTED_HMAC')
                package.loaded['cosock']={socket={udp=function()
                    local sock={payload=nil}
                    function sock:settimeout(_) end
                    function sock:setoption(k,v) assert(k=='broadcast' and v==true); return 1 end
                    function sock:sendto(payload,host,port)
                        assert(host=='192.168.50.255' and port==9)
                        assert(#payload==102)
                        assert(payload:sub(1,6)==string.rep(string.char(255),6))
                        return #payload
                    end
                    function sock:close() end
                    return sock
                end}}
                local wol=require 'computerhost.wol'
                assert(wol.packet('00:11:22:33:44:55') and #wol.packet('00:11:22:33:44:55')==102)
                assert(not wol.packet('ff:ff:ff:ff:ff:ff'))
                assert(wol.send('00:11:22:33:44:55','192.168.50.255',9))
            '''
            import hmac,hashlib
            expected=hmac.new(bytes.fromhex('01'*32), ('POST\n/v2/power/reboot\n'+'a'*48+'\n').encode(),hashlib.sha256).hexdigest()
            code=(code.replace('EXPECTED_HMAC',expected) % (repr(str(ROOT)),repr(str(ROOT))))
            st=lib.luaL_loadstring(vm,code.encode())
            if st==0: st=lib.lua_pcallk(vm,0,0,0,0,None)
            error=lib.lua_tolstring(vm,-1,None).decode(errors='replace') if st else ''
            self.assertEqual(st,0,error)
        finally:
            lib.lua_close(vm)
