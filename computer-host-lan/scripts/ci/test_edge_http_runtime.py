"""Run the real Edge HTTP module against pinned upstream cosock and LuaSocket.

CI-only integration: no hub, external network traffic, credentials or power
operations. Only SmartThings JSON decoding and logging are replaced by stubs.
"""
import argparse
import json
import os
from pathlib import Path
import socketserver
import subprocess
import threading

ROOT = Path(__file__).resolve().parents[2]
BODY = json.dumps(dict(protocol='computer-host-agent', api_version=2,
                       id='aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
                       platform='linux', status='running'), separators=(',', ':')).encode('ascii')


class Listener(socketserver.ThreadingTCPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, mode):
        self.mode = mode
        self.closed_by_client = threading.Event()
        self.errors = []
        super().__init__(('127.0.0.1', 0), Handler)


class Handler(socketserver.StreamRequestHandler):
    def handle(self):
        self.connection.settimeout(12)
        try:
            if not self.rfile.readline(4096).startswith(b'GET /v2/health HTTP/'):
                raise AssertionError('unexpected HTTP request')
            for _ in range(64):
                if self.rfile.readline(4096) == b'\r\n':
                    break
            else:
                raise AssertionError('request headers not terminated')
            header = (b'HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n'
                      + b'Content-Length: ' + str(len(BODY)).encode() + b'\r\nConnection: close\r\n')
            mode = self.server.mode
            if mode == 'drip-header':
                self.connection.sendall(header + b'X-Slow: ')
            elif mode == 'normal':
                self.connection.sendall(header + b'\r\n' + BODY)
            else:
                self.connection.sendall(header + b'\r\n' + BODY[:1])
            if mode in ('drip-header', 'drip-body'):
                # Frequent bytes stay well inside the inactivity limit, but
                # neither the header line nor the body completes in 8 s.
                import select
                for _ in range(44):
                    readable, _, _ = select.select([self.connection], [], [], 0.25)
                    if readable and self.connection.recv(1) == b'':
                        self.server.closed_by_client.set()
                        return
                    self.connection.sendall(b'x')
                raise AssertionError('client did not terminate slow response')
            # Keep the connection open ourselves. EOF proves the client closed
            # it, rather than simply returning a timeout and leaking a socket.
            if self.connection.recv(1) != b'':
                raise AssertionError('unexpected data after request')
            self.server.closed_by_client.set()
        except (ConnectionResetError, BrokenPipeError):
            self.server.closed_by_client.set()
        except Exception as exc:
            self.server.errors.append(str(exc))


LUA = r'''
local root,upstream,mode,port,body=arg[1],arg[2],arg[3],tonumber(arg[4]),arg[5]
package.path=upstream..'/?.lua;'..upstream..'/?/init.lua;'..root..'/?.lua;'..root..'/?/init.lua;'..package.path
local native=require 'socket'
local report=print
print=function() end -- upstream scheduler's very verbose debug output
local cosock=require 'cosock'
-- Keep a strong reference to the real TCP socket, without replacing any
-- native methods. Check its descriptor BEFORE Lua exits (OS cleanup alone
-- would otherwise make the Python peer's EOF assertion insufficient).
local tcp=cosock.socket.tcp
local owned={}
cosock.socket.tcp=function(...)
  local sock,err=tcp(...)
  if sock then owned[#owned+1]=sock end
  return sock,err
end
local diagnostics={}
package.loaded['log']={error=function(message) diagnostics[#diagnostics+1]=message end}
package.loaded['st.json']={decode=function(value)
  assert(value==body,'response body differs')
  return {protocol='computer-host-agent',api_version=2,id='aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',platform='linux',status='running'}
end}
local api=require 'computerhost.api'
local presence=require 'computerhost.presence'
local finished=false
cosock.spawn(function()
  local start=native.gettime()
  local data,err=api.fetch_health('127.0.0.1',port)
  local elapsed=native.gettime()-start
  assert(#diagnostics==0,'unexpected deadline compatibility fallback')
  assert(#owned==1 and owned[1]:getfd()==-1,'owned TCP socket not closed before return')
  if mode=='normal' then
    assert(data and data.status=='running',tostring(err))
    assert(elapsed<4,'normal response too slow')
  else
    assert(not data and type(err)=='string',tostring(err))
    assert(presence.classify_failure(err)=='host_unreachable',err)
    if mode=='stall-body' then
      assert(elapsed>=3.5 and elapsed<6, 'inactivity timeout: '..elapsed..' '..err)
    else
      assert(err:find('HTTP request deadline exceeded',1,true),err)
      assert(elapsed>=7.5 and elapsed<10, 'cumulative deadline: '..elapsed)
    end
  end
  report(string.format('PASS %s %.3f seconds (%s)',mode,elapsed,tostring(err or 'running')))
  finished=true
end,'Computer Host native HTTP integration')
cosock.run()
assert(finished,'scheduler exited before request completed')
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cosock-dir', required=True, type=Path)
    parser.add_argument('--lua', default='lua5.4')
    args = parser.parse_args()
    env = {k: v for k, v in os.environ.items() if k.lower() not in
           ('http_proxy', 'https_proxy', 'all_proxy', 'lua_path', 'lua_cpath')}
    for mode in ('normal', 'drip-header', 'stall-body', 'drip-body'):
        with Listener(mode) as server:
            worker = threading.Thread(target=server.serve_forever, daemon=True)
            worker.start()
            try:
                result = subprocess.run([args.lua, '-e', 'assert(_VERSION=="Lua 5.4")', '-',
                                         str(ROOT / 'edge-driver' / 'src'), str(args.cosock_dir.resolve()),
                                         mode, str(server.server_address[1]), BODY.decode('ascii')],
                                        input=LUA, text=True, capture_output=True, env=env, timeout=15)
                print(result.stdout, end='', flush=True)
                if result.returncode:
                    raise AssertionError(result.stderr)
                if not server.closed_by_client.wait(2) or server.errors:
                    raise AssertionError(f'{mode}: peer closure not verified: {server.errors}')
                print(f'PASS {mode}: server observed client close', flush=True)
            finally:
                server.shutdown()
                worker.join(2)


if __name__ == '__main__':
    main()
