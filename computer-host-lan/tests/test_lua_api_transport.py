"""Exercise the real Edge API module with HTTP and cosock scheduler doubles.

The doubles model LuaSocket's timeout overwrite and repeated cosock readiness
waits within one operation; virtual time makes slow-byte tests deterministic.
These are not real-hub or native socket-library integration tests.
"""
import ctypes
from lua_runtime import load_lua
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1] / "edge-driver" / "src"


class LuaHTTPTransportTests(unittest.TestCase):
    def run_lua(self, script):
        lib = load_lua(self)
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

        script = ("package.path = %s .. '/?.lua;' .. %s .. '/?/init.lua;' .. package.path\n"
                  % (repr(str(ROOT)), repr(str(ROOT)))) + script
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

    def test_module_timeout_is_not_overwritten_by_luasocket(self):
        self.run_lua(r"""
            local socket_http = { TIMEOUT = 60 }
            local socket_object = {}
            local created_timeout, effective_timeout, request_count
            local challenge_code, power_code=200,202

            function socket_object:settimeout(seconds)
                self.timeout = seconds
                return 1
            end

            function socket_object:close() return 1 end

            local cosock = {
                socket = {
                    tcp = function() return socket_object end,
                    gettime = function() return 100 end,
                    select = function() error('unexpected wait') end
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
                        status = 'running',
                        nonce = string.rep('a',48), accepted=true, action='shutdown'
                    }
                end
            }

            package.loaded['computerhost.constants'] = {
                HTTP_TIMEOUT = 4,
                HTTP_TOTAL_DEADLINE = 8,
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
                created_timeout = socket_object.timeout
                sock:settimeout(socket_http.TIMEOUT)
                effective_timeout = socket_object.timeout
                request.sink('{}')
                local code=200
                if request.url:find('/v2/challenge',1,true) then code=challenge_code end
                if request.url:find('/v2/power/',1,true) then code=power_code end
                return 1, code, {}, 'HTTP response'
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
            local uuid='aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'
            local key=string.rep('0',64)
            challenge_code=403
            local ok, err, status=api.control('127.0.0.1',8765,uuid,key,'shutdown')
            assert(not ok and status==403 and err:find('HTTP status 403',1,true))
            assert(request_count==2) -- no POST after challenge refusal
            challenge_code=200
            power_code=403
            ok,err,status=api.control('127.0.0.1',8765,uuid,key,'shutdown')
            assert(not ok and status==403 and err:find('HTTP status 403',1,true))
            assert(request_count==4)
            power_code=409
            ok,err,status=api.control('127.0.0.1',8765,uuid,key,'shutdown')
            assert(not ok and status==409)
            power_code=202
            assert(api.control('127.0.0.1',8765,uuid,key,'shutdown'))
        """)


    DEADLINE_FIXTURE = r"""

            local C=require 'computerhost.constants'
            local presence=require 'computerhost.presence'
            assert(C.HTTP_TIMEOUT==4 and C.HTTP_TOTAL_DEADLINE==8)
            local epoch,clock=1800000000,0
            local milliseconds=false
            local closed,created,completed=0,0,0
            local plan,waits={},{}
            local mode='normal'
            local http={TIMEOUT=60}
            local raw
            local function op(self,kind,pattern)
                local stages=pattern and plan[pattern] or plan[kind]
                for _,stage in ipairs(stages or {}) do
                    if stage=='buffered' then
                        clock=clock+3
                    else
                        -- Mirrors cosock.socket.internals.passthroughbuilder:
                        -- *one* operation can wait repeatedly, keeping self.timeout.
                        local reads=kind=='receive' and {self} or {}
                        local writes=kind~='receive' and {self} or {}
                        local _,_,err=coroutine.yield(reads,writes,self.timeout)
                        if err then return nil,err,'partial' end
                    end
                end
                return kind=='receive' and 'response' or 1
            end
            package.loaded['cosock']={
                socket={
                    gettime=function()
                        return (epoch+clock)*(milliseconds and 1000 or 1)
                    end,
                    tcp=function()
                        created=created+1
                        raw={
                            settimeout=function(self,t) self.timeout=t; return 1 end,
                            close=function(self)
                                assert(not self.closed,'double close')
                                self.closed=true; closed=closed+1; return 1
                            end,
                            connect=function(self) return op(self,'connect') end,
                            send=function(self) return op(self,'send') end,
                            receive=function(self,pattern) return op(self,'receive',pattern) end,
                        }
                        return raw
                    end,
                    select=function(reads,writes,timeout)
                        -- The outer managed coroutine yields to its scheduler;
                        -- these must be the raw cosock sockets, not proxies.
                        return coroutine.yield(reads,writes,timeout)
                    end,
                },
                asyncify=function(name) assert(name=='socket.http'); return http end,
            }
            package.loaded['st.json']={decode=function(body)
                assert(body=='{}')
                return {protocol='computer-host-agent',api_version=2,
                        id='aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',platform='linux',status='running'}
            end}
            function http.request(request)
                assert(request.redirect==false)
                local sock=assert(request.create())
                assert(sock:settimeout(http.TIMEOUT))
                local ok,err=sock:connect('127.0.0.1',8765)
                if not ok then return nil,err end
                ok,err=sock:send('GET /v2/health HTTP/1.1\r\n\r\n')
                if not ok then return nil,err end
                if mode=='exception' then error('injected parser error') end
                for i=1,(mode=='many_headers' and 10 or 1) do
                    ok,err=sock:receive('*l')
                    if not ok then return nil,err end
                end
                if mode=='body' then
                    ok,err=sock:receive(2)
                    if not ok then return nil,err end
                end
                if mode=='late_sink' then clock=clock+9 end
                ok,err=request.sink(mode=='oversize' and string.rep('x',32769) or '{}')
                if not ok then return nil,err end
                assert(request.sink(nil))
                sock:close()
                completed=completed+1
                return 1,200,{},'HTTP response'
            end
            local api=require 'computerhost.api'
            local function run(stages,scenario,arrival)
                plan=stages; mode=scenario or 'normal'; clock=0; waits={}
                local before_created,before_closed=created,closed
                local thread=coroutine.create(function()
                    return api.fetch_health('127.0.0.1',8765)
                end)
                local args=table.pack()
                while true do
                    local r=table.pack(coroutine.resume(thread,table.unpack(args,1,args.n)))
                    assert(r[1],tostring(r[2]))
                    if coroutine.status(thread)=='dead' then
                        assert(created==before_created+1 and closed==before_closed+1,
                               'each created socket must be closed exactly once')
                        return r[2],r[3]
                    end
                    local reads,writes,timeout=r[2],r[3],r[4]
                    assert((reads[1] or writes[1])==raw,'wrong socket passed to scheduler')
                    assert(timeout>0 and timeout<=4 and timeout<=8-clock,
                           'wait exceeded remaining request budget')
                    waits[#waits+1]=timeout
                    local delay=arrival or 3
                    if scenario=='backwards_clock' then
                        clock=clock-1
                        args=table.pack(reads,writes,nil)
                    elseif delay>=timeout then
                        clock=clock+timeout
                        args=table.pack(nil,nil,'timeout')
                    else
                        clock=clock+delay
                        args=table.pack(reads,writes,nil)
                    end
                end
            end
            local function expect_deadline(stages,scenario,arrival)
                local before=completed
                local data,err=run(stages,scenario,arrival)
                assert(not data and err:find('HTTP request deadline exceeded',1,true),tostring(err))
                assert(presence.classify_failure(err)=='host_unreachable')
                assert(completed==before,'expired request completed later')
            end
        """

    def test_single_receive_cannot_renew_deadline(self):
        self.run_lua(self.DEADLINE_FIXTURE + r"""
            expect_deadline({receive={1,1,1,1}})
            assert(clock==8 and #waits==3 and waits[1]==4 and waits[2]==4 and waits[3]==2)
        """)

    def test_numeric_body_receive_cannot_renew_deadline(self):
        self.run_lua(self.DEADLINE_FIXTURE + r"""
            expect_deadline({[2]={1,1,1,1}},'body')
            assert(clock==8 and #waits==3)
        """)

    def test_deadline_spans_connect_send_and_read(self):
        self.run_lua(self.DEADLINE_FIXTURE + r"""
            expect_deadline({connect={1},send={1},receive={1}})
            assert(clock==8 and #waits==3)
            expect_deadline({send={1,1,1,1}})
            assert(clock==8 and #waits==3)
            local data,err=run({connect={1},send={1},receive={1}},'normal',1)
            assert(data and not err and clock==3 and #waits==3)
        """)

    def test_inactivity_timeout_still_four_seconds(self):
        self.run_lua(self.DEADLINE_FIXTURE + r"""
            local data,err=run({receive={1}},'normal',10)
            assert(not data and err=='HTTP transport failed: timeout',tostring(err))
            assert(clock==4 and #waits==1)
            assert(presence.classify_failure(err)=='host_unreachable')
        """)

    def test_buffered_header_reads_sink_and_exception_cleanup(self):
        self.run_lua(self.DEADLINE_FIXTURE + r"""
            expect_deadline({receive={'buffered'}},'many_headers')
            expect_deadline({},'late_sink')
            local data,err=run({},'oversize')
            assert(not data and err:find('response too large',1,true))
            data,err=run({},'exception')
            assert(not data and err:find('injected parser error',1,true))
            assert(run({},'normal')) -- no stale state on subsequent requests
        """)

    def test_epoch_milliseconds_and_backwards_clock(self):
        self.run_lua(self.DEADLINE_FIXTURE + r"""
            milliseconds=true
            expect_deadline({receive={1,1,1,1}})
            assert(clock==8 and #waits==3)
            milliseconds=false
            expect_deadline({receive={1}},'backwards_clock')
            assert(#waits==1)
            assert(run({},'normal'))
        """)


if __name__ == "__main__":
    unittest.main()
