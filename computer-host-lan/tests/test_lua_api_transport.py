"""Regression: the SmartThings Lua HTTP transport must retain its configured timeout.

LuaSocket's socket.http.open() applies socket.http.TIMEOUT after the driver's
custom create callback. This test executes the real api.lua module with a
small socket.http double that reproduces that ordering.
"""
import ctypes
from ctypes.util import find_library
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1] / "edge-driver" / "src"


class LuaHTTPTransportTests(unittest.TestCase):
    def test_module_timeout_is_not_overwritten_by_luasocket(self):
        library = find_library("lua5.4") or find_library("lua5.3")
        if not library:
            self.skipTest("Lua runtime library unavailable")

        lib = ctypes.CDLL(library)
        lib.luaL_newstate.restype = ctypes.c_void_p
        lib.luaL_openlibs.argtypes = [ctypes.c_void_p]
        lib.luaL_loadstring.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
        lib.luaL_loadstring.restype = ctypes.c_int
        lib.lua_pcallk.argtypes = [
            ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_int,
            ctypes.c_ssize_t, ctypes.c_void_p,
        ]
        lib.lua_pcallk.restype = ctypes.c_int
        lib.lua_tolstring.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p]
        lib.lua_tolstring.restype = ctypes.c_char_p
        lib.lua_close.argtypes = [ctypes.c_void_p]

        script = r"""
            package.path = %s .. '/?.lua;' .. %s .. '/?/init.lua;' .. package.path

            local socket_http = { TIMEOUT = 60 }
            local socket_object = {}
            local created_timeout, effective_timeout, request_count

            function socket_object:settimeout(seconds)
                self.timeout = seconds
                return 1
            end

            local cosock = {
                socket = {
                    tcp = function() return socket_object end
                },
                asyncify = function(name)
                    assert(name == 'socket.http')
                    return socket_http
                end
            }
            package.loaded['cosock'] = cosock

            package.loaded['st.json'] = {
                decode = function(body)
                    assert(body == '{}')
                    return {
                        protocol = 'computer-host-agent',
                        api_version = 2,
                        id = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
                        platform = 'linux',
                        status = 'running'
                    }
                end
            }

            package.loaded['computerhost.constants'] = {
                HTTP_TIMEOUT = 4,
                DRIVER_VERSION = '0.4.5-rc.1',
                PROTOCOL_NAME = 'computer-host-agent',
                PROTOCOL_VERSION = 2
            }
            package.loaded['computerhost.util'] = {
                parse_host_port = function(host, port) return host, port end,
                host_for_url = function(host) return host end,
                uuid_valid = function(value)
                    return value == 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'
                end
            }
            package.loaded['computerhost.sha256'] = {
                hmac_hex = function() return string.rep('0', 64) end
            }

            -- Mirrors LuaSocket http.open(): create() runs first, then
            -- socket.http.TIMEOUT is applied to the returned socket.
            function socket_http.request(request)
                request_count = (request_count or 0) + 1
                local sock = request.create()
                created_timeout = sock.timeout
                sock:settimeout(socket_http.TIMEOUT)
                effective_timeout = sock.timeout
                request.sink('{}')
                return 1, 200, {}, 'HTTP/1.1 200 OK'
            end

            local api = require 'computerhost.api'
            local health, err = api.fetch_health('127.0.0.1', 8765)
            assert(health, tostring(err))
            assert(health.status == 'running')
            assert(socket_http.TIMEOUT == 4,
                   'socket.http.TIMEOUT was not set to the driver timeout')
            assert(created_timeout == 4,
                   'custom socket create callback did not set the expected timeout')
            assert(effective_timeout == 4,
                   'LuaSocket overwrote the socket timeout with a different value')
            assert(request_count == 1)
        """ % (repr(str(ROOT)), repr(str(ROOT)))

        vm = lib.luaL_newstate()
        try:
            lib.luaL_openlibs(vm)
            status = lib.luaL_loadstring(vm, script.encode())
            if status == 0:
                status = lib.lua_pcallk(vm, 0, 0, 0, 0, None)
            error = lib.lua_tolstring(vm, -1, None).decode(errors="replace") if status else ""
            self.assertEqual(status, 0, error)
        finally:
            lib.lua_close(vm)


if __name__ == "__main__":
    unittest.main()
