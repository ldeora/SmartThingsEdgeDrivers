-- Minimal SHA-256 + HMAC-SHA256 in pure Lua 5.3+; no external hub modules.
-- Intended for short SmartThings LAN request signatures, not bulk file hashing.
local M = {}
local MASK = 0xffffffff
local K = {
  0x428a2f98,0x71374491,0xb5c0fbcf,0xe9b5dba5,0x3956c25b,0x59f111f1,0x923f82a4,0xab1c5ed5,
  0xd807aa98,0x12835b01,0x243185be,0x550c7dc3,0x72be5d74,0x80deb1fe,0x9bdc06a7,0xc19bf174,
  0xe49b69c1,0xefbe4786,0x0fc19dc6,0x240ca1cc,0x2de92c6f,0x4a7484aa,0x5cb0a9dc,0x76f988da,
  0x983e5152,0xa831c66d,0xb00327c8,0xbf597fc7,0xc6e00bf3,0xd5a79147,0x06ca6351,0x14292967,
  0x27b70a85,0x2e1b2138,0x4d2c6dfc,0x53380d13,0x650a7354,0x766a0abb,0x81c2c92e,0x92722c85,
  0xa2bfe8a1,0xa81a664b,0xc24b8b70,0xc76c51a3,0xd192e819,0xd6990624,0xf40e3585,0x106aa070,
  0x19a4c116,0x1e376c08,0x2748774c,0x34b0bcb5,0x391c0cb3,0x4ed8aa4a,0x5b9cca4f,0x682e6ff3,
  0x748f82ee,0x78a5636f,0x84c87814,0x8cc70208,0x90befffa,0xa4506ceb,0xbef9a3f7,0xc67178f2,
}
local function ror(x,n) return ((x >> n) | ((x << (32-n)) & MASK)) & MASK end
function M.digest(message)
  local len=#message
  message=message..string.char(0x80)
  message=message..string.rep("\0",(56-(#message%64))%64)..string.pack(">I8",len*8)
  local h={0x6a09e667,0xbb67ae85,0x3c6ef372,0xa54ff53a,
    0x510e527f,0x9b05688c,0x1f83d9ab,0x5be0cd19}
  for pos=1,#message,64 do
    local w={}
    for i=1,16 do w[i]=string.unpack(">I4",message,pos+(i-1)*4) end
    for i=17,64 do
      local x,y=w[i-15],w[i-2]
      local s0=ror(x,7) ~ ror(x,18) ~ (x >> 3)
      local s1=ror(y,17) ~ ror(y,19) ~ (y >> 10)
      w[i]=(w[i-16]+s0+w[i-7]+s1)&MASK
    end
    local a,b,c,d,e,f,g,hh=table.unpack(h)
    for i=1,64 do
      local s1=ror(e,6) ~ ror(e,11) ~ ror(e,25)
      local ch=(e&f) ~ ((~e)&g)
      local t1=(hh+s1+ch+K[i]+w[i])&MASK
      local s0=ror(a,2) ~ ror(a,13) ~ ror(a,22)
      local maj=(a&b) ~ (a&c) ~ (b&c)
      local t2=(s0+maj)&MASK
      hh,g,f,e,d,c,b,a=g,f,e,(d+t1)&MASK,c,b,a,(t1+t2)&MASK
    end
    for i,x in ipairs({a,b,c,d,e,f,g,hh}) do h[i]=(h[i]+x)&MASK end
  end
  local result={}
  for _,x in ipairs(h) do result[#result+1]=string.pack(">I4",x) end
  return table.concat(result)
end
function M.hex(bytes) return (bytes:gsub(".",function(x) return string.format("%02x",x:byte()) end)) end
function M.hmac_hex(hexkey,message)
  if type(hexkey)~="string" or #hexkey~=64 or not hexkey:match("^[0-9a-fA-F]+$") then return nil end
  local key=hexkey:gsub("..",function(x) return string.char(tonumber(x,16)) end)
  key=key..string.rep("\0",64-#key)
  local inner,outer={},{}
  for i=1,64 do
    local b=key:byte(i)
    inner[i]=string.char(b~0x36)
    outer[i]=string.char(b~0x5c)
  end
  return M.hex(M.digest(table.concat(outer)..M.digest(table.concat(inner)..message)))
end
return M
